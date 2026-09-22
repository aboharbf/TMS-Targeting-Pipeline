import subprocess
import logging
import os
import re
import pandas as pd
from datetime import datetime
from pathlib import Path

# === Define a reusable log directory ===
logDir = Path("~/pipeline/scripts/logs").expanduser()
logDir.mkdir(exist_ok=True)

# === Create a timestamped session log file ===
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = logDir / f"session_{timestamp}.log"

# === Configure file-only logger ===
file_logger = logging.getLogger('file_only')
file_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(log_path)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
file_logger.addHandler(file_handler)
file_logger.propagate = False  # Prevent propagation to root logger

def run_and_log(command, shell=True):
    """
    Run a bash command, show output live, and log stdout/stderr separately.
    - Logs stored in logDir/session_<timestamp>.log
    - If stdout is empty, skip it.
    - Prefix each stderr line with 'ERROR:' in both terminal and log.
    """
    file_logger.info(f"RUN: {command}")
    print(f"\033[1;36m[RUN]\033[0m {command}")  # Cyan in terminal

    process = subprocess.Popen(
        command,
        shell=shell,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    out, _ = process.communicate()

    if out.strip():
        for line in out.strip().splitlines():
            print(line)
            file_logger.info(line)
    
    # Only log as error if command failed
    if process.returncode != 0:
        file_logger.error(f"COMMAND FAILED WITH RETURN CODE: {process.returncode}\n")
        print(f"\033[1;31mERROR:\033[0m Command failed with return code {process.returncode}")
    else:
        file_logger.info(f"RETURN CODE: {process.returncode}\n")

    return {
        "returncode": process.returncode,
        "stdout": out.strip().splitlines() if out.strip() else [],
        "stderr": []
    }


def print_and_log(message):
    """
    Print a message to stdout and write it to the session log, without
    spawning a shell the way run_and_log("echo ...") does.
    """
    print(message)
    file_logger.info(message)


def spaceTagFromTemplate(tlrcBase):
    """
    Space field of the preprocessing base name, derived from the afni_proc
    -tlrc_base template. Add an elif per new template, each with its own tag.
    """
    if os.path.basename(tlrcBase) == 'MNI152_2009_template.nii.gz':
        return 'mni'
    raise ValueError(f"no space tag defined for tlrcBase '{tlrcBase}'")


def preprocNames(subj, ses, task, seqType, spaceTag, runTag=''):
    """
    Names shared by the preprocessing outputs and everything that reads them.

    Scheme: {subj}_ses-{ses}_task-{task}_{space}[_{tag}] . {seqType} . {stage} . {ext}
        job script  {scriptId}.job.sh
        job logs    {scriptId}.job.o/.e
        proc script {scriptId}.proc.csh
        temp dir    {baseId}.delete
        results dir {scriptId}
        errts       {scriptId}/errts.{subjId}.tproject+tlrc

    Returns:
        dict with baseId, scriptId and subjId (afni_proc -subj_id)
    """
    if '_' in runTag:
        raise ValueError(f"runTag '{runTag}' must not contain '_'")
    tagSfx = f"_{runTag}" if runTag else ''
    baseId = f"{subj}_ses-{ses}_task-{task}_{spaceTag}{tagSfx}"
    return {
        'baseId': baseId,
        'scriptId': f"{baseId}.{seqType}",
        'subjId': f"{subj}_ses-{ses}",
    }


def resolveErrts(dataDir, subj, ses, task, seqType, spaceTag, runTag='', ext='.BRIK'):
    """
    Path to a session's errts file, trying the current preprocNames scheme
    first and falling back to the pre-rename (f06) name:
        {subj}.results.task-{task}-{space}.{seqType}/errts.{subj}.tproject+tlrc
    The old names carry no run tag, so a fallback hit is untagged output.

    Returns:
        (path, isLegacy). If neither exists, the current-scheme path and False.
    """
    names = preprocNames(subj, ses, task, seqType, spaceTag, runTag)
    sesDir = f"{dataDir}/{subj}/ses-{ses}"
    newPath = f"{sesDir}/{names['scriptId']}/errts.{names['subjId']}.tproject+tlrc{ext}"
    legacyPath = f"{sesDir}/{subj}.results.task-{task}-{spaceTag}.{seqType}/errts.{subj}.tproject+tlrc{ext}"

    if os.path.exists(newPath) or not os.path.exists(legacyPath):
        return newPath, False
    return legacyPath, True


class slurmScriptLogger:
    """
    A class to manage SLURM script generation and command logging.

    Attributes:
        script_id (str): Caller-supplied identifier for the script
        job_name (str): --job-name written into the SBATCH header
        script_dir (str): Directory where the script will be stored
        script_path (str): Full path to the script file
    """

    def __init__(self, script_id, script_dir,
                 cpus_per_task=1, mem="16G", time="24:00:00",
                 job_name=None, file_prefix="slurm_job", file_suffix="",
                 description="Automated Cluster detection pipeline"):
        """
        Initialize the SlurmScriptLogger.

        Args:
            script_id (str): Identifier built by the caller, used for the script
                filename and stamped into the script header
            script_dir (str): Directory where scripts will be stored
            cpus_per_task (int): --cpus-per-task for the SBATCH header
            mem (str): --mem for the SBATCH header (total, not per-cpu)
            time (str): --time for the SBATCH header, HH:MM:SS
            job_name (str): --job-name for the SBATCH header, defaults to script_id
            file_prefix (str): prepended to the script filename with a '-';
                None or '' for no prefix
            file_suffix (str): appended to script_id before '.sh' (e.g. '.job')
            description (str): free text written into the script header
        """
        self.script_id = script_id
        self.cpus_per_task = cpus_per_task
        self.mem = mem
        self.time = time
        self.job_name = job_name if job_name else script_id
        self.description = description
        self.script_dir = script_dir
        prefix = f"{file_prefix}-" if file_prefix else ""
        self.script_filename = f"{prefix}{self.script_id}{file_suffix}.sh"
        self.script_path = os.path.join(script_dir, self.script_filename)

        # Ensure directory exists
        os.makedirs(self.script_dir, exist_ok=True)

        # Initialize the script file with header if it doesn't exist
        self._initialize_script()

    def _initialize_script(self):
        """
        Create the script file with SLURM header if it doesn't already exist.
        This is called automatically during initialization.
        """

       # Remove existing script if it exists
        if os.path.exists(self.script_path):
            os.remove(self.script_path)

        header = f"""#!/bin/bash
#SBATCH --job-name={self.job_name}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={self.cpus_per_task}
#SBATCH --time={self.time}
#SBATCH --mem={self.mem}
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
## Script Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
## Script ID: {self.script_id}
## Description: {self.description}
## Author: Farid Aboharb, Balderston Lab

"""
        with open(self.script_path, 'w') as f:
            f.write(header)

    def append(self, command):
        """
        Append a command to the SLURM script file.
        
        Args:
            command (str): Bash command to append to the script
        """
        with open(self.script_path, 'a') as f:
            f.write(f"{command}\n")

def extract_filename_variables(filename):
    """
    Extract variables from filename using split.
    Expected format: subjectNumber.sessionNumber.task.sequenceType.1d
    Example: 101.2.nback.random.1d -> subject=101, session=2, task=rest, sequence=random
    """
    # Remove file extension first
    name_without_ext = filename.rsplit('.', 1)[0]  # Remove last extension (.1d)
    
    # Split by periods
    parts = name_without_ext.split('.')
    print(parts)

    result = {}
    if len(parts) >= 4:
        result['subject'] = parts[0]
        result['session'] = parts[1]
        result['task'] = parts[2]
        result['sequence_type'] = parts[3]
    else:
        result['subject'] = None
        result['session'] = None
        result['task'] = None
        result['sequence_type'] = None
    
    # Extract field after 'targ', which defines target activity source.
    result['target'] = None
    try:
        targ_index = parts.index('targ')
        if targ_index + 1 < len(parts):
            result['target'] = parts[targ_index + 1]
    except ValueError:
        pass  # 'targ' not found in parts
    
    # Extract 1st and 2nd fields after another string (e.g., 'seed')
    # Change 'seed' to whatever string you need
    search_string = 'clust'
    result['clustRegion'] = None
    result['clustMask'] = None
    try:
        search_index = parts.index(search_string)
        if search_index + 1 < len(parts):
            result['clustRegion'] = parts[search_index + 1]
        if search_index + 2 < len(parts):
            result['clustMask'] = parts[search_index + 2]
    except ValueError:
        pass  # search_string not found in parts

    return result

def extract_numbers_from_file(filepath):
    """
    Extract 3 numbers from file content.
    Adjust based on your file format.
    """
    with open(filepath, 'r') as f:
        content = f.read()
        # Example: extract all numbers from file
        numbers = re.findall(r'[-+]?\d*\.?\d+', content)

        # Return first 3 numbers (adjust as needed)
        if len(numbers) >= 3:
            return {
                'X': float(numbers[0]),
                'Y': float(numbers[1]),
                'Z': float(numbers[2])
            }
    return {'X': None, 'Y': None, 'Z': None}

def process_folder(folder_path):
    """
    Recursively process all .1d files in folder and subdirectories.
    """
    data = []

    # Walk through all directories and subdirectories
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            # Only process files with .1d extension
            if not ('fisher' in filename and filename.endswith('.1d')):
                continue

            filepath = os.path.join(root, filename)

            # Extract data from filename and file content
            row_data = {}
            row_data['filename'] = filename
            row_data['filepath'] = filepath  # Store full path for reference
            row_data.update(extract_filename_variables(filename))
            row_data.update(extract_numbers_from_file(filepath))
            print(row_data)
            data.append(row_data)

            # Optional: print progress
            print(f"Processed: {filepath}")

    # Create DataFrame
    df = pd.DataFrame(data)
    return df
