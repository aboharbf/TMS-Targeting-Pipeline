"""
Submit x07.blur_censor_param.csh for every finished base run, to rebuild errts over a
grid of blur sizes x motion censor limits. 

This script picks subjects/sessions and parameter lists and writes one small
SLURM job per subject-session; f07 does all the AFNI work. Variants already
done are skipped here and again inside f07, so re-running is safe.

Variant naming matches f07 and utils.preprocNames: the variant run tag is the
base run tag plus '-b{F}m{M}' ('.' -> 'p'), e.g. 'param' -> 'param-b4m0p3',
so peakScript.py / fileCheck.py read a variant by setting runTag to that.
"""

import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

from utils import slurmScriptLogger, spaceTagFromTemplate, preprocNames

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = f'{projDir}/nbthetaconn/data'                             # Inputs; only used for the subject list.
outputDir = f'{projDir}/nbthetaconn/analysis_out/pipeline_params'    # preprocScript.py's output root; must match.

workerScript = f'{projDir}/pipeline/scripts/x07.blur_censor_param.csh'       # The tcsh worker, as deployed on the server.

slurmScriptDir = f'{projDir}/pipeline/slurm_post'

# sbatch .o/.e files go in a fresh subdir per invocation of this script.
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
slurmLogDir = f'{slurmScriptDir}/logs_{timestamp}'

# -------------------------------------------------------------- configuration
runTag = 'param'                        # Run tag of the BASE run to start from (preprocScript.py's runTag).

task = 'rest'
seqTypeVec = ['me']                     # first '.' field after the base name; also the results dir suffix
sesVec = ['01', '02', '03', '04']

tlrcBase = 'MNI152_2009_template.nii.gz'
spaceTag = spaceTagFromTemplate(tlrcBase)

# Parameter grid. Strings, written exactly as they should appear in the names
# ('4', not 4.0), since f07 builds the same names from the same text.
fwhmVec = ['0', '2', '4', '6', '8']                   # 3dBlurInMask -FWHM; '0' = no blur
motVec = ['0', '0.15', '0.3', '0.45', '0.6']          # 1d_tool.py -censor_motion limit

cpus = 4                                # --cpus-per-task and OMP_NUM_THREADS
memPerJob = '16G'                       # TOTAL memory; 3dpc holds both runs at once
timePerJob = '04:00:00'                 # whole grid for one subject-session

dryRun = False                          # True = report only, write nothing.
submit = True                           # True = sbatch each script as it's written, False = write only.
maxJobs = 200                           # Wait while more than this many of your jobs are queued.
waitSec = 60                            # How long to sleep between queue checks.


def variantTag(fwhm, mot):
    """Variant part of the run tag, as f07 builds it: b{F}m{M}, '.' -> 'p'."""
    return f"b{fwhm}m{mot}".replace('.', 'p')


def variantRunTag(fwhm, mot):
    """Full run tag of a variant; f07 joins it to an untagged base with '_' instead."""
    tag = variantTag(fwhm, mot)
    return f"{runTag}-{tag}" if runTag else tag


# ------------------------------------------------------------------- subjects
subjVec = [item for item in os.listdir(dataDir)
           if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# As a test, just do the first one
subjVec = subjVec[0:1]

print(f"Preparing scripts on following subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}")
print(f"Grid: fwhm {fwhmVec} x motion {motVec} = {len(fwhmVec) * len(motVec)} variants per subject/session/seqType")

if not os.path.isfile(workerScript):
    raise FileNotFoundError(f"worker script not found: {workerScript}")

nGenerated = 0
nSubmitted = 0
nDone = 0
nSkipped = 0
nActive = 0

# Names of our queued/running jobs, so a session isn't submitted twice.
# Only queried when submitting, so the script runs off-cluster otherwise.
activeJobs = set()
if submit and not dryRun:
    activeJobs = set(subprocess.run(["squeue", "--me", "-h", "-o", "%j"], capture_output=True,
                                    text=True, check=True).stdout.split())

for subj in subjVec:
    for ses in sesVec:
        for seqType in seqTypeVec:

            # Base run names
            names = preprocNames(subj, ses, task, seqType, spaceTag, runTag)
            scriptId = names['scriptId']
            subjId = names['subjId']
            jobId = f"{scriptId}.post"                      # Stem of the job script, logs, job name.

            outputSesDir = f"{outputDir}/{subj}/ses-{ses}"
            meDir = f"{outputSesDir}/{scriptId}"            # Base results dir; f07's <resdir>.
            doneFile = f"{meDir}/out.ss_review.{subjId}.txt"

            if not os.path.exists(doneFile):
                print(f"{subj} ses-{ses} {seqType}: no finished base run ({doneFile}) - skipping")
                nSkipped += 1
                continue

            # Inputs f07 reads; it checks these too, but finding out here saves a queue wait.
            needed = [f"pb04.{subjId}.r{run}.combine+tlrc.HEAD" for run in ('01', '02')] + [
                f"mask_epi_anat.{subjId}+tlrc.HEAD",
                "mask_WMe_resam+tlrc.HEAD",
                "mask_CSFe_resam+tlrc.HEAD",
                "dfile_rall.1D",
                f"outcount_{subjId}_censor.1D",
            ]
            missing = [f for f in needed if not os.path.exists(f"{meDir}/{f}")]
            if missing:
                print(f"{subj} ses-{ses} {seqType}: base run lacks f07 inputs (run without the preserve mv lines?) - skipping")
                for f in missing:
                    print(f"  {f}")
                nSkipped += 1
                continue

            # Variants with no errts yet; the same check f07 makes.
            todo = []
            for fwhm in fwhmVec:
                for mot in motVec:
                    varNames = preprocNames(subj, ses, task, seqType, spaceTag, variantRunTag(fwhm, mot))
                    varErrts = f"{outputSesDir}/{varNames['scriptId']}/errts.{subjId}.tproject+tlrc.HEAD"
                    if not os.path.exists(varErrts):
                        todo.append(variantTag(fwhm, mot))
            if not todo:
                print(f"{subj} ses-{ses} {seqType}: all {len(fwhmVec) * len(motVec)} variants done - skipping")
                nDone += 1
                continue

            if jobId in activeJobs:
                print(f"{subj} ses-{ses} {seqType}: job {jobId} already queued/running - skipping")
                nActive += 1
                continue

            if dryRun:
                print(f"{subj} ses-{ses} {seqType}: would generate job script ({len(todo)} variants to do: {' '.join(todo)})")
                nGenerated += 1
                continue

            # --------------------------------------------------------- job script
            logger = slurmScriptLogger(
                jobId, slurmScriptDir,
                cpus_per_task=cpus,
                mem=memPerJob,
                time=timePerJob,
                job_name=jobId,
                file_prefix=None,
                file_suffix=".job",
                description="Blur x motion-censor variants from a finished afni_proc run (f07)",
            )

            # Full lists, not just todo: f07 skips finished variants itself, and
            # still needs every motion limit's censor branch for the blurs it redoes.
            logger.append(f"""module unload python
module load python/anaconda/3.9.2

export OMP_NUM_THREADS={cpus}

tcsh -xef {workerScript} {meDir} "{' '.join(fwhmVec)}" "{' '.join(motVec)}"
""")

            print(f"{subj} ses-{ses} {seqType}: wrote {logger.script_path} ({len(todo)} variants to do)")
            nGenerated += 1

            # ------------------------------------------------------------- submit
            if submit:
                while True:
                    queue = subprocess.run(["squeue", "--me", "-h"], capture_output=True,
                                           text=True, check=True).stdout
                    numJobs = len(queue.splitlines())
                    if numJobs <= maxJobs:
                        break
                    print(f"waiting for other jobs to finish ({numJobs} queued)")
                    time.sleep(waitSec)

                # sbatch won't create the log dir, so make it before submitting.
                os.makedirs(slurmLogDir, exist_ok=True)
                os.chmod(logger.script_path, 0o777)
                subprocess.run(["sbatch",
                                f"--output={slurmLogDir}/{jobId}.job.o",
                                f"--error={slurmLogDir}/{jobId}.job.e",
                                logger.script_path], check=True)
                nSubmitted += 1


print(f"\nGenerated {nGenerated} job script(s) in {slurmScriptDir}")
print(f"  {nDone} subject/session/seqType(s) with every variant done")
print(f"  {nActive} subject/session/seqType(s) already queued/running")
print(f"  {nSkipped} subject/session/seqType(s) skipped (no finished base run, or missing f07 inputs)")
if submit and not dryRun:
    print(f"Submitted {nSubmitted} job(s); check them with: squeue --me")
    if nSubmitted:
        print(f"Job .o/.e files will be in {slurmLogDir}")
print("\nVariant run tags (set runTag in peakScript.py / fileCheck.py to read one):")
for fwhm in fwhmVec:
    print("  " + "  ".join(variantRunTag(fwhm, mot) for mot in motVec))
