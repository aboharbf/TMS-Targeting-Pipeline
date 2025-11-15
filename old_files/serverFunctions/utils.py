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


class slurmScriptLogger:
    """
    A class to manage SLURM script generation and command logging.
    
    Attributes:
        subject_number (str): Subject identifier
        session (str): Session identifier
        task (str): Task identifier
        sequence (str): Sequence identifier
        script_id (str): Combined identifier for the script
        script_dir (str): Directory where the script will be stored
        script_path (str): Full path to the script file
    """
    
    def __init__(self, subject_number, session, task, sequence, script_dir):
        """
        Initialize the SlurmScriptLogger.
        
        Args:
            subject_number (str): Subject identifier
            session (str): Session identifier
            task (str): Task identifier
            sequence (str): Sequence identifier
            script_dir (str): Directory where scripts will be stored
        """
        self.subject_number = subject_number
        self.session = session
        self.task = task
        self.sequence = sequence
        self.script_id = f"{subject_number}.{session}.{task}.{sequence}"
        self.script_dir = script_dir
        self.script_filename = f"slurm_job-{self.script_id}.sh"
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

        info_str = f"Subject.Session.Task.Sequence - {self.script_id}"
        header = f"""#!/bin/bash
#SBATCH --job-name=plu{self.subject_number}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=24:00:00
#SBATCH --mem=16G
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
## Script Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
## Description: Automated Cluster detection pipeline for {info_str}
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
