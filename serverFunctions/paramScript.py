"""
Submit x07.blur_censor_param.csh for every finished base run, to rebuild errts over a
grid of blur sizes x motion censor limits. 

This script picks subjects/sessions and parameter lists and writes one small
SLURM job per subject (and seqType), which runs f07 on each of that subject's
ready sessions in turn; f07 does all the AFNI work. Variants already done are
skipped here and again inside f07, so re-running is safe.

Variant naming matches f07 and utils.preprocNames: the variant run tag is the
base run tag plus '-b{F}m{M}' ('.' -> 'p'), e.g. 'param' -> 'param-b4m0p3',
so peakScript.py reads a variant by that run tag.
"""

import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

import analysisConfig as cfg
from utils import (slurmScriptLogger, spaceTagFromTemplate, preprocNames, variantRunTag,
                   snapshotConfig, preprocPaths, preprocSession, paramSession)

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = cfg.dataDir                   # Inputs; only used for the subject list.
outputDir = cfg.outputDir               # preprocScript.py's output root.

workerScript = f'{projDir}/pipeline/scripts/x07.blur_censor_param.csh'       # The tcsh worker, as deployed on the server.

slurmScriptDir = f'{projDir}/pipeline/slurm_post'

# sbatch .o/.e files go in a fresh subdir per invocation of this script.
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
slurmLogDir = f'{slurmScriptDir}/logs_{timestamp}'

# -------------------------------------------------------------- configuration
# Shared and analysis settings come from analysisConfig.py.
snapshotConfig(cfg)

runTag = cfg.runTag                     # Run tag of the BASE run to start from.
task = cfg.task
seqTypeVec = cfg.seqTypeVec
sesVec = cfg.sesVec
spaceTag = spaceTagFromTemplate(cfg.tlrcBase)

fwhmVec = cfg.fwhmVec                   # The grid; see analysisConfig.py.
motVec = cfg.motVec

cpus = cfg.paramCpus                    # --cpus-per-task and OMP_NUM_THREADS
memPerJob = cfg.paramMem                # TOTAL memory
timePerJob = cfg.paramTime

dryRun = False                          # True = report only, write nothing.
submit = True                           # True = sbatch each script as it's written, False = write only.
maxJobs = 200                           # Wait while more than this many of your jobs are queued.
waitSec = 60                            # How long to sleep between queue checks.


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
nSesQueued = 0
nDone = 0
nSkipped = 0
nActive = 0

# Names of our queued/running jobs, so a subject isn't submitted twice.
# Only queried when submitting, so the script runs off-cluster otherwise.
activeJobs = set()
if submit and not dryRun:
    activeJobs = set(subprocess.run(["squeue", "--me", "-h", "-o", "%j"], capture_output=True,
                                    text=True, check=True).stdout.split())

for subj in subjVec:
    for seqType in seqTypeVec:

        # One job per subject: the base run name without its '_ses-{ses}' field.
        # Stem of the job script, logs and job name.
        tagSfx = f"_{runTag}" if runTag else ''
        jobId = f"{subj}_task-{task}_{spaceTag}{tagSfx}.{seqType}.post"

        if jobId in activeJobs:
            print(f"{subj} {seqType}: job {jobId} already queued/running - skipping")
            nActive += 1
            continue

        # Sessions ready for f07: (ses, base results dir, variants to do)
        readySes = []
        for ses in sesVec:

            # Base run names
            names = preprocNames(subj, ses, task, seqType, spaceTag, runTag)
            scriptId = names['scriptId']

            paths = preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, runTag)
            meDir = paths['meDir']                          # Base results dir; f07's <resdir>.

            # Base run outputs, checked by utils.preprocSession, the same rules
            # pipelineCheck.py reports with.
            pre = preprocSession(outputDir, subj, ses, task, seqType, spaceTag, runTag)

            if not pre['done']:
                print(f"{subj} ses-{ses} {seqType}: no finished base run ({paths['doneFile']}) - skipping")
                nSkipped += 1
                continue

            # Inputs f07 reads; it checks these too, but finding out here saves a queue wait.
            if pre['missingInputs']:
                print(f"{subj} ses-{ses} {seqType}: base run lacks f07 inputs (run without the preserve mv lines?) - skipping")
                for f in pre['missingInputs']:
                    print(f"  {f}")
                nSkipped += 1
                continue

            # Variants with no errts yet, checked by utils.paramSession: the same
            # check f07 makes, and the one pipelineCheck.py reports with.
            par = paramSession(outputDir, subj, ses, task, seqType, spaceTag, runTag, fwhmVec, motVec)
            todo = par['todo']
            if par['skipped']:
                print(f"{subj} ses-{ses} {seqType}: {len(par['skipped'])} variants skipped by x07 "
                      f"(too few TRs after censoring): {' '.join(par['skipped'])}")
            if not todo:
                print(f"{subj} ses-{ses} {seqType}: all {len(fwhmVec) * len(motVec)} variants done or skipped - skipping")
                nDone += 1
                continue

            # A per-session job from before this script grouped sessions by subject.
            if f"{scriptId}.post" in activeJobs:
                print(f"{subj} ses-{ses} {seqType}: job {scriptId}.post already queued/running - skipping")
                nActive += 1
                continue

            readySes.append((ses, meDir, todo))

        if not readySes:
            continue

        sesList = ' '.join(f"ses-{ses}" for ses, _, _ in readySes)
        if dryRun:
            print(f"{subj} {seqType}: would generate job script {jobId} for {sesList}")
            for ses, _, todo in readySes:
                print(f"  ses-{ses}: {len(todo)} variants to do: {' '.join(todo)}")
            nGenerated += 1
            nSesQueued += len(readySes)
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
            description=f"Blur x motion-censor variants from finished afni_proc runs (f07), sessions run in turn: {sesList}",
        )

        # mark() writes to both .o and .e, so each session's stretch of the
        # tcsh -x trace (which goes to .e) is easy to find. A failed session
        # doesn't stop the later ones, but fails the job at the end.
        logger.append(f"""module unload python
module load python/anaconda/3.9.2

export OMP_NUM_THREADS={cpus}

mark() {{ echo "$*"; echo "$*" >&2; }}
status=0
""")

        # Full lists, not just todo: f07 skips finished variants itself, and
        # still needs every motion limit's censor branch for the blurs it redoes.
        for ses, meDir, todo in readySes:
            logger.append(f"""mark "===== {subj} ses-{ses} {seqType}: start $(date)"
tcsh -xef {workerScript} {meDir} "{' '.join(fwhmVec)}" "{' '.join(motVec)}" \\
    || {{ rc=$?; status=1; mark "===== {subj} ses-{ses} {seqType}: FAILED (exit $rc)"; }}
mark "===== {subj} ses-{ses} {seqType}: end $(date)"
""")

        logger.append("exit $status")

        print(f"{subj} {seqType}: wrote {logger.script_path}")
        for ses, _, todo in readySes:
            print(f"  ses-{ses}: {len(todo)} variants to do")
        nGenerated += 1
        nSesQueued += len(readySes)

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


print(f"\nGenerated {nGenerated} job script(s) in {slurmScriptDir}, covering {nSesQueued} subject/session/seqType(s)")
print(f"  {nDone} subject/session/seqType(s) with every variant done")
print(f"  {nActive} subject(s) or subject/session(s) already queued/running")
print(f"  {nSkipped} subject/session/seqType(s) skipped (no finished base run, or missing f07 inputs)")
if submit and not dryRun:
    print(f"Submitted {nSubmitted} job(s); check them with: squeue --me")
    if nSubmitted:
        print(f"Job .o/.e files will be in {slurmLogDir}")
print("\nVariant run tags:")
for fwhm in fwhmVec:
    print("  " + "  ".join(variantRunTag(runTag, fwhm, mot) for mot in motVec))
