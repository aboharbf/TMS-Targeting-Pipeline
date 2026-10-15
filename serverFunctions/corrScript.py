"""
Submit the sgACC -> dlPFC peak search for every run tag (the base run and each
paramScript.py grid variant) whose errts is ready. This is peakScript.py, batched
into SLURM jobs the way paramScript.py does it.

One SLURM job per subject (and seqType), which works through each session's
todo run tags in turn. For each run tag and sgACC mask: 3dmaskave (sgACC trace)
-> 3dTcorr1D (whole-brain Fisher z) -> for each dlPFC mask and peak sign
(analysisConfig.peakSignExpr: peakScript.py's |z|, plus negative and positive
correlations separately), 3dcalc (mask) -> 3dclust (top cluster's peak).
Steps 1-3 and the 'abs' outputs' names are peakScript.py's.

Each clust .1d is one line, 'X Y Z z': the peak's RAI coordinates and its Fisher
z (negative for 'neg'; |z| for 'abs'), or 'none' when the map has no cluster of
that sign. mergeOutputs.py reads these into X/Y/Z/peakZ, empty for 'none'.

Run tags already done are skipped here (utils.corrSession, the same check
pipelineCheck.py's corr report uses), and each command is skipped in the job if
its output is there, so re-running is safe. A failed command is marked in both
the .o and .e logs and fails the job at the end, but doesn't stop it: later
masks, run tags and sessions still run.
"""

import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

import analysisConfig as cfg
from utils import (slurmScriptLogger, spaceTagFromTemplate, errtsPrefix, variantRunTag,
                   snapshotConfig, corrPaths, corrSession)

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = cfg.dataDir                   # Inputs; only used for the subject list.
outputDir = cfg.outputDir               # preprocScript.py's output root; errts are read from here.
resultsDir = cfg.resultsDir             # Outputs, one subdir per subject.

slurmScriptDir = f'{projDir}/pipeline/slurm_corr'

# sbatch .o/.e files go in a fresh subdir per invocation of this script.
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
slurmLogDir = f'{slurmScriptDir}/logs_{timestamp}'

# -------------------------------------------------------------- configuration
# Shared and analysis settings come from analysisConfig.py.
task = cfg.task
seqTypeVec = cfg.seqTypeVec
sesVec = cfg.sesVec
spaceTag = spaceTagFromTemplate(cfg.tlrcBase)

# Which preprocessing outputs to read: the base run, then every grid variant
# (paramScript.py), so all of them are compared under the same peak search.
runTag = cfg.runTag
runTagVec = [runTag] + [variantRunTag(runTag, fwhm, mot) for fwhm in cfg.fwhmVec for mot in cfg.motVec]

# Full paths for the sgACC target masks and the dlPFC cluster search masks.
maskTypeVec = cfg.maskTypeVec
maskPathVec = [cfg.sgaccMaskTemplate.format(maskT) for maskT in maskTypeVec]
clustMaskVec = cfg.clustMaskVec
clustMaskPathVec = [cfg.clustMaskTemplate.format(cMask) for cMask in clustMaskVec]
signVec = list(cfg.peakSignExpr)        # peak searches per dlPFC mask: 'abs', 'neg', 'pos'

cpus = cfg.corrCpus                     # --cpus-per-task and OMP_NUM_THREADS
memPerJob = cfg.corrMem                 # TOTAL memory
timePerJob = cfg.corrTime

dryRun = False                          # True = report only, write nothing.
submit = True                           # True = sbatch each script as it's written, False = write only.
maxJobs = 200                           # Wait while more than this many of your jobs are queued.
waitSec = 60                            # How long to sleep between queue checks.


# ------------------------------------------------------------------- subjects
subjVec = [item for item in os.listdir(dataDir)
           if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# As a test, just do the first 10
subjVec = subjVec[0:10]

# Record the config next to the session log and in each subject's results folder.
snapshotConfig(cfg, extraDirs=[] if dryRun else [f"{resultsDir}/{subj}" for subj in subjVec])

print(f"Preparing scripts on following subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}")
print(f"{len(runTagVec)} run tags x {len(maskTypeVec)} sgACC masks x {len(clustMaskVec)} dlPFC masks "
      f"x {len(signVec)} peak signs ({' '.join(signVec)}) per subject/session/seqType")

for maskPath in maskPathVec + clustMaskPathVec:
    if not os.path.isfile(maskPath):
        raise FileNotFoundError(f"mask not found: {maskPath}")

nGenerated = 0
nSubmitted = 0
nSesQueued = 0
nDone = 0
nNotReady = 0
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
        # Stem of the job script, logs and job name; paramScript.py's job is the same stem + '.post'.
        tagSfx = f"_{runTag}" if runTag else ''
        jobStem = f"{subj}_task-{task}_{spaceTag}{tagSfx}.{seqType}"
        jobId = f"{jobStem}.corr"

        if jobId in activeJobs:
            print(f"{subj} {seqType}: job {jobId} already queued/running - skipping")
            nActive += 1
            continue

        # Its variants are still being made; wait, rather than search half a grid now and the rest later.
        if f"{jobStem}.post" in activeJobs:
            print(f"{subj} {seqType}: paramScript job {jobStem}.post still queued/running - skipping")
            nActive += 1
            continue

        # Sessions with run tags to do: (ses, todo run tags)
        readySes = []
        for ses in sesVec:

            # Outputs and errts per run tag, checked by utils.corrSession.
            cor = corrSession(outputDir, resultsDir, subj, ses, task, seqType, spaceTag,
                              runTagVec, maskTypeVec, clustMaskVec, signVec)

            if cor['notReady']:
                print(f"{subj} ses-{ses} {seqType}: no errts yet for {len(cor['notReady'])} of "
                      f"{len(runTagVec)} run tags, leaving those for later: {' '.join(cor['notReady'])}")

            if not cor['todo']:
                if cor['notReady']:
                    nNotReady += 1
                else:
                    print(f"{subj} ses-{ses} {seqType}: all {len(runTagVec)} run tags done - skipping")
                    nDone += 1
                continue

            readySes.append((ses, cor['todo']))

        if not readySes:
            continue

        sesList = ' '.join(f"ses-{ses}" for ses, _ in readySes)
        if dryRun:
            print(f"{subj} {seqType}: would generate job script {jobId} for {sesList}")
            for ses, todo in readySes:
                print(f"  ses-{ses}: {len(todo)} run tags to do: {' '.join(todo)}")
            nGenerated += 1
            nSesQueued += len(readySes)
            continue

        os.makedirs(f"{resultsDir}/{subj}", exist_ok=True)

        # --------------------------------------------------------- job script
        logger = slurmScriptLogger(
            jobId, slurmScriptDir,
            cpus_per_task=cpus,
            mem=memPerJob,
            time=timePerJob,
            job_name=jobId,
            file_prefix=None,
            file_suffix=".job",
            description=f"sgACC -> dlPFC peak search over run tags (3dmaskave, 3dTcorr1D, 3dcalc, 3dclust), sessions run in turn: {sesList}",
        )

        # mark() writes to both .o and .e, so each step is easy to find in
        # AFNI's messages (which go to .e). fail() records a failed command
        # (its exit code is still $? when fail starts) without stopping the job.
        # clustOk() is utils.clustDone's test: first line 'none', or 4 fields with a number.
        logger.append(f"""export OMP_NUM_THREADS={cpus}

mark() {{ echo "$*"; echo "$*" >&2; }}
fail() {{ rc=$?; status=1; mark "FAILED (exit $rc): $*"; }}
clustOk() {{ [ -f "$1" ] && awk 'NR == 1 {{ok = ($1 == "none" && NF == 1) || (NF == 4 && /[0-9]/)}} END {{exit !ok}}' "$1"; }}
status=0
""")

        for ses, todo in readySes:
            logger.append(f'mark "===== {subj} ses-{ses} {seqType}: start $(date), {len(todo)} run tags"')

            for tag in todo:
                errtsFile = errtsPrefix(outputDir, subj, ses, task, seqType, spaceTag, tag)
                logger.append(f'mark "### {subj} ses-{ses} run tag {tag}"')

                for tMask, maskPath in zip(maskTypeVec, maskPathVec):

                    # Step 1 - average across the sgACC mask, creating a single time series.
                    # The redirect makes the file even when 3dmaskave fails, so remove it then.
                    avgPath = corrPaths(resultsDir, subj, ses, task, seqType, tag, tMask, clustMaskVec[0])['avg']
                    logger.append(f"[ -f {avgPath} ] || 3dmaskave -quiet -mask {maskPath} {errtsFile} > {avgPath} "
                                  f"|| {{ fail \"{subj} ses-{ses} {tag} {tMask}: 3dmaskave\"; rm -f {avgPath}; }}")

                    for cMask, cMaskPath in zip(clustMaskVec, clustMaskPathVec):
                        corrPath = corrPaths(resultsDir, subj, ses, task, seqType, tag, tMask, cMask)['corr']
                        label = f"{subj} ses-{ses} {tag} {tMask}/{cMask}"

                        # Step 2 - correlate with the whole brain.
                        logger.append(f"[ -f {corrPath} ] || 3dTcorr1D -Fisher -prefix {corrPath} {errtsFile} {avgPath} "
                                      f"|| fail \"{label}: 3dTcorr1D\"")

                        for sign, expr in cfg.peakSignExpr.items():
                            paths = corrPaths(resultsDir, subj, ses, task, seqType, tag, tMask, cMask, sign)
                            corrMaskPath = paths['corrMask']    # masked to the dlPFC mask, this sign only
                            corrClustOutPath = paths['clust']   # the top cluster's peak
                            signLabel = f"{label} {sign}"

                            # Step 3 - mask by the dlPFC.
                            logger.append(f"[ -f {corrMaskPath} ] || 3dcalc -a {corrPath} -b {cMaskPath} "
                                          f"-expr \"{expr}\" -prefix {corrMaskPath} "
                                          f"|| fail \"{signLabel}: 3dcalc\"")

                            # Step 4 - the top cluster's peak. 3dclust lists clusters
                            # largest first; awk takes the first one's max-intensity
                            # location (MI RL/AP/IS, columns 14-16) and value (Max Int,
                            # column 13), by column so leading spaces don't matter.
                            # The 'neg' map holds -z, so its value is flipped back.
                            # 3dclust failing is a failure (retried next run); 3dclust
                            # running but listing no cluster writes 'none' (done).
                            peakZ = '-$13' if sign == 'neg' else '$13'
                            logger.append(f"""if ! clustOk {corrClustOutPath}; then
    3dclust -quiet -orient RAI -1clip .01 3.5 2 {corrMaskPath} > {corrClustOutPath}.raw; rc=$?
    if [ $rc -ne 0 ]; then
        status=1; mark "FAILED (exit $rc): {signLabel}: 3dclust"
    else
        awk 'NF >= 16 && $1 ~ /^[0-9.]+$/ {{print $14, $15, $16, {peakZ}; exit}}' {corrClustOutPath}.raw > {corrClustOutPath}.tmp
        if clustOk {corrClustOutPath}.tmp; then
            mv {corrClustOutPath}.tmp {corrClustOutPath}
        else
            echo none > {corrClustOutPath}
        fi
        echo "{signLabel}: $(cat {corrClustOutPath})"
    fi
    rm -f {corrClustOutPath}.raw {corrClustOutPath}.tmp
fi""")

                        logger.append(f'mark "Completed {label}"')

            logger.append(f'mark "===== {subj} ses-{ses} {seqType}: end $(date)"\n')

        logger.append("exit $status")

        print(f"{subj} {seqType}: wrote {logger.script_path}")
        for ses, todo in readySes:
            print(f"  ses-{ses}: {len(todo)} run tags to do")
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
print(f"  {nDone} subject/session/seqType(s) with every run tag done")
print(f"  {nNotReady} subject/session/seqType(s) with nothing ready (run tags left have no errts yet)")
print(f"  {nActive} subject(s) already queued/running, or waiting on their paramScript job")
if submit and not dryRun:
    print(f"Submitted {nSubmitted} job(s); check them with: squeue --me")
    if nSubmitted:
        print(f"Job .o/.e files will be in {slurmLogDir}")
