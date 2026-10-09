import subprocess
import logging
import os
import re
import glob
import json
import shutil
import hashlib
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


def snapshotConfig(cfg, extraDirs=()):
    """
    Copy the config module this run imported (pass the module itself) next to
    the session log, and into each of extraDirs (created if needed), as
    session_<timestamp>.<name>.py, and log its source path and sha256.
    Copying cfg.__file__ guarantees the copy is the file actually used, not
    another one of the same name. The timestamp matches the session log's, so
    copies from different runs never overwrite each other.
    """
    src = Path(cfg.__file__)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    print_and_log(f"Config: {src} (sha256 {digest})")
    for d in [logDir, *extraDirs]:
        os.makedirs(d, exist_ok=True)
        dst = Path(d) / f"session_{timestamp}.{src.name}"
        shutil.copy2(src, dst)
        print_and_log(f"  saved to {dst}")


def spaceTagFromTemplate(tlrcBase):
    """
    Space field of the preprocessing base name, derived from the afni_proc
    -tlrc_base template. Add an elif per new template, each with its own tag.
    """
    if os.path.basename(tlrcBase) == 'MNI152_2009_template.nii.gz':
        return 'mni'
    raise ValueError(f"no space tag defined for tlrcBase '{tlrcBase}'")


def rawT1(dataDir, subj):
    """
    The subject's T1 (afni_proc -copy_anat), sorted; preprocScript.py uses the
    first match, so an empty list means missing.
    """
    return sorted(glob.glob(f"{dataDir}/{subj}/anat/{subj}_T1fs_conform.nii*"))


def rawSession(dataDir, subj, ses, task, nEchoes):
    """
    Find and check one session's raw inputs, by the rules preprocScript.py applies
    before writing a job. pipelineCheck.py reports the same result, so 'found'
    there means preprocScript will accept the session.

    Rules: run-01 and run-02 each have exactly nEchoes echo files, and run-01 has
    nEchoes sidecars that all hold an EchoTime. run-02's sidecars aren't used, so
    their count is only noted.

    Returns a dict:
        checks     list of (item, status, detail), in report order; status is
                   'found', 'missing' (none there), 'bad' (wrong count or
                   unreadable) or 'note' (not used by preprocScript, so not blocking)
        problems   'missing/bad item (detail)' per blocking check; empty = usable
        run1epi, run2epi   echo files, sorted so they line up with echoTimes
        echoTimes  run-01 echo times in ms, as strings for -echo_times
    """
    sesDir = f"{dataDir}/{subj}/ses-{ses}"
    out = {'checks': [], 'problems': [], 'run1epi': [], 'run2epi': [], 'echoTimes': []}

    def check(item, status, detail=''):
        out['checks'].append((item, status, detail))
        if status in ('missing', 'bad'):
            out['problems'].append(f"{status} {item} ({detail})" if detail else f"{status} {item}")

    if not os.path.isdir(sesDir):
        check('session directory', 'missing')
        return out

    # sorted() everywhere below: glob returns directory order, which is
    # arbitrary on the server, and the echoes have to stay lined up with the
    # echo times read further down.
    for run, key in (('01', 'run1epi'), ('02', 'run2epi')):
        epis = sorted(glob.glob(f"{sesDir}/func_task-{task}_run-{run}*ap_e?.nii"))
        out[key] = epis
        if not epis:
            check(f"run-{run}", 'missing')
        elif len(epis) != nEchoes:
            check(f"run-{run}", 'bad', f"{len(epis)} echoes, need {nEchoes}")
        else:
            check(f"run-{run}", 'found', f"{len(epis)} echoes")

    # Echo times in ms, read straight out of the run-01 BIDS sidecars.
    jsons = sorted(glob.glob(f"{sesDir}/func_task-{task}_run-01*ap_e?.json"))
    unreadable = []
    for jsonPath in jsons:
        try:
            with open(jsonPath) as fh:
                echoTimeSec = json.load(fh)["EchoTime"]
            out['echoTimes'].append(f"{round(echoTimeSec * 1000, 4):g}")
        except (OSError, ValueError, KeyError, TypeError):
            unreadable.append(os.path.basename(jsonPath))
    if not jsons:
        check('run-01 sidecars', 'missing')
    elif unreadable:
        check('run-01 sidecars', 'bad', f"no readable EchoTime in {', '.join(unreadable)}")
    elif len(jsons) != nEchoes:
        check('run-01 sidecars', 'bad', f"{len(jsons)}, need {nEchoes}")
    else:
        check('run-01 sidecars', 'found', f"EchoTime {' '.join(out['echoTimes'])} ms")

    jsons2 = glob.glob(f"{sesDir}/func_task-{task}_run-02*ap_e?.json")
    if len(jsons2) == nEchoes:
        check('run-02 sidecars', 'found', f"{len(jsons2)}")
    else:
        check('run-02 sidecars', 'note', f"{len(jsons2)}, expected {nEchoes}")

    return out


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


def variantTag(fwhm, mot):
    """Variant part of a grid run tag, as x07 builds it: b{F}m{M}, '.' -> 'p'."""
    return f"b{fwhm}m{mot}".replace('.', 'p')


def variantRunTag(runTag, fwhm, mot):
    """Full run tag of a grid variant of base run runTag; x07 joins it to an untagged base with '_' instead."""
    tag = variantTag(fwhm, mot)
    return f"{runTag}-{tag}" if runTag else tag


def decodeRunTag(tag, baseTag, baseFwhm, baseMotion):
    """
    fwhm and motion censor limit a run tag stands for, as floats; (None, None) if unknown.
    A grid variant ends in variantTag's 'b{F}m{M}' ('p' -> '.'). The base run tag
    carries no values, so baseFwhm/baseMotion (its afni_proc settings) are used.
    An empty tag (results named before the run tag was added) is unknown.
    """
    if not tag:
        return None, None
    match = re.search(r'(?:^|-)b(\d+(?:p\d+)?)m(\d+(?:p\d+)?)$', tag)
    if match:
        return float(match.group(1).replace('p', '.')), float(match.group(2).replace('p', '.'))
    if tag == baseTag:
        return float(baseFwhm), float(baseMotion)
    return None, None


def errtsPrefix(outputDir, subj, ses, task, seqType, spaceTag, runTag=''):
    """
    AFNI prefix of a session's errts dataset under outputDir (preprocScript.py's
    output root), named by preprocNames. There is deliberately no fallback to other
    names: the caller checks f"{prefix}.HEAD" (the .BRIK may or may not be gzipped)
    and treats a missing file as missing.
    """
    return preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, runTag)['errts']


def preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, runTag=''):
    """
    Paths of a session's preprocessing outputs under outputDir (preprocScript.py's
    output root), named by preprocNames. Naming only: nothing is checked on disk.

    Returns a dict:
        outputSesDir   {outputDir}/{subj}/ses-{ses}; afni_proc runs from here
        meDir          results dir, {scriptId}
        workDir        afni_proc -out_dir, {baseId}.delete; deleted by the cleanup
        doneFile       out.ss_review in meDir, the evidence of completion
        errts          AFNI prefix of the errts in meDir (no .HEAD/.BRIK)
    """
    names = preprocNames(subj, ses, task, seqType, spaceTag, runTag)
    outputSesDir = f"{outputDir}/{subj}/ses-{ses}"
    meDir = f"{outputSesDir}/{names['scriptId']}"
    return {
        'outputSesDir': outputSesDir,
        'meDir': meDir,
        'workDir': f"{outputSesDir}/{names['baseId']}.delete",
        'doneFile': f"{meDir}/out.ss_review.{names['subjId']}.txt",
        'errts': f"{meDir}/errts.{names['subjId']}.tproject+tlrc",
    }


def preprocSession(outputDir, subj, ses, task, seqType, spaceTag, runTag=''):
    """
    Check one session's base-run outputs: what preprocScript.py's job leaves in
    the results dir after afni_proc and its cleanup. Paths come from
    preprocPaths; this only looks at what's on disk. preprocScript.py
    skips a session that's 'done', paramScript.py starts the grid only from one
    with no missingInputs, and pipelineCheck.py reports the same result.

    Rules: the results dir holds out.ss_review (afni_proc's last output, so the
    run finished), the errts (what peakScript.py reads), and the files
    x07.blur_censor_param.csh rebuilds the grid from (kept by the cleanup's
    preserve mv lines). A leftover working dir ({baseId}.delete) means a run
    failed or is still going; it's only noted.

    Returns a dict:
        checks     list of (item, status, detail), in report order; status is
                   'found', 'missing' or 'note' (not blocking), as rawSession
        problems   'missing item (detail)' per missing check; empty = complete
        done       out.ss_review is there (preprocScript's skip test)
        missingInputs   x07 inputs not in the results dir
    """
    subjId = preprocNames(subj, ses, task, seqType, spaceTag, runTag)['subjId']
    paths = preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, runTag)
    meDir = paths['meDir']
    out = {'checks': [], 'problems': [], 'done': False, 'missingInputs': []}

    def check(item, status, detail=''):
        out['checks'].append((item, status, detail))
        if status in ('missing', 'bad'):
            out['problems'].append(f"{status} {item} ({detail})" if detail else f"{status} {item}")

    if not os.path.isdir(meDir):
        check('results dir', 'missing', os.path.basename(meDir))
    else:
        out['done'] = os.path.exists(paths['doneFile'])
        check('out.ss_review', 'found' if out['done'] else 'missing')

        check('errts', 'found' if os.path.exists(f"{paths['errts']}.HEAD") else 'missing')

        # What x07 reads from the results dir; it checks these too.
        inputs = [f"pb04.{subjId}.r{run}.combine+tlrc.HEAD" for run in ('01', '02')] + [
            f"mask_epi_anat.{subjId}+tlrc.HEAD",
            "mask_WMe_resam+tlrc.HEAD",
            "mask_CSFe_resam+tlrc.HEAD",
            "dfile_rall.1D",
            f"outcount_{subjId}_censor.1D",
        ]
        out['missingInputs'] = [f for f in inputs if not os.path.exists(f"{meDir}/{f}")]
        if out['missingInputs']:
            check('x07 inputs', 'missing',
                  f"{len(out['missingInputs'])} of {len(inputs)}: {', '.join(out['missingInputs'])}")
        else:
            check('x07 inputs', 'found', f"{len(inputs)} files")

    if os.path.isdir(paths['workDir']):
        check('working dir', 'note', f"{os.path.basename(paths['workDir'])} left in place: run failed or still going")

    return out


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
    Expected format: subjectNumber.sessionNumber.task.sequenceType[.runTag].errts....1d
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

    # 5th field is the run tag; names from before it was added have 'errts' there.
    result['runTag'] = parts[4] if len(parts) >= 5 and parts[4] != 'errts' else ''

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
