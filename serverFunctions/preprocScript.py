import os
import glob
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path

from utils import slurmScriptLogger, spaceTagFromTemplate, preprocNames

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = f'{projDir}/nbthetaconn/data'

slurmScriptDir = f'{projDir}/pipeline/slurm_preproc'

# sbatch .o/.e files go in a fresh subdir per invocation of this script.
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
slurmLogDir = f'{slurmScriptDir}/logs_{timestamp}'

# -------------------------------------------------------------- configuration
runTag = 'noclean'                      # Marks this pipeline run's outputs; last '_' field of the base name.
                                        # No '_' allowed (use '-'), so names split cleanly. '' = no tag.

task = 'rest'
seqType = 'me'                          # first '.' field after the base name; also the results dir suffix
sesVec = ['01', '02', '03', '04']       # assume all subjects have 4 sessions

jobs = 16                               # -jobs for 3dDeconvolve, and --cpus-per-task
memPerCpu = 16                          # GB per CPU, same as f06's --mem-per-cpu=16G
memPerJob = f'{memPerCpu * jobs}G'      # TOTAL memory (256G at 16 jobs).
timePerJob = '24:00:00'

tlrcBase = 'MNI152_2009_template.nii.gz'
firstTRs = 4
spaceTag = spaceTagFromTemplate(tlrcBase)   # 'mni' for the MNI152_2009 template.

# File/dir naming lives in utils.preprocNames:
#   job script  {scriptId}.job.sh      (slurmScriptDir)
#   job logs    {scriptId}.job.o/.e    (slurmLogDir)
#   proc script {scriptId}.proc.csh    (codeDir)
#   temp dir    {baseId}.delete        (sesDir)
#   results dir {scriptId}             (sesDir)

dryRun = False                          # True = report only, make sure all the req'd files are present.
submit = True                           # True = sbatch each script as it's written (as f06 does), False = write only.
maxJobs = 200                           # Wait while more than this many of your jobs are queued (f06's maxjobs).
waitSec = 60                            # How long to sleep between queue checks (f06's sleep 60).

# ------------------------------------------------------------------- subjects
subjVec = [item for item in os.listdir(dataDir)
           if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# As a test, just do the first few
subjVec = subjVec[0:1]

print(f"Preparing scripts on following subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}")


nGenerated = 0
nSubmitted = 0
nDone = 0
nSkipped = 0

for subj in subjVec:
    for ses in sesVec:

        # Input
        sesDir = f"{dataDir}/{subj}/ses-{ses}"

        # Names
        names = preprocNames(subj, ses, task, seqType, spaceTag, runTag)
        baseId = names['baseId']
        scriptId = names['scriptId']                    # Stem of the job script, logs, proc script, job name.
        subjId = names['subjId']                        # afni_proc -subj_id; names the files inside the results dir.

        # Script Outputs
        codeDir = f"{dataDir}/{subj}/code"              # Where the afni proc script ends up.

        # Afni_proc outputs
        outDir = f"{sesDir}/{baseId}.delete"            # Temporary dir, files moved, ends up deleted.
        meDir = f"{sesDir}/{scriptId}"                  # Where the useful things end up.
        doneFile = f"{meDir}/out.ss_review.{subjId}.txt"    # Evidence of completion.

        # Determine the session directory is there.
        if not os.path.isdir(sesDir):
            print(f"{subj} ses-{ses}: no session directory - skipping")
            nSkipped += 1
            continue

        # Check if things ran already
        if os.path.exists(doneFile):
            print(f"{subj} ses-{ses}: already processed - skipping")
            nDone += 1
            continue

        # Grab the T1
        t1Vec = sorted(glob.glob(f"{dataDir}/{subj}/anat/{subj}_T1fs_conform.nii*"))
        if not t1Vec:
            print(f"{subj}: no T1 found - skipping ses-{ses}")
            nSkipped += 1
            continue

        # Grab the epis.
        # sorted() everywhere below: glob returns directory order, which is
        # arbitrary on the server, and the echoes have to stay lined up with the
        # echo times read further down.
        run1epi = sorted(glob.glob(f"{sesDir}/func_task-{task}_run-01*ap_e?.nii"))
        run2epi = sorted(glob.glob(f"{sesDir}/func_task-{task}_run-02*ap_e?.nii"))
        if not run1epi or not run2epi:
            print(f"{subj} ses-{ses}: missing EPIs "
                  f"(run-01: {len(run1epi)}, run-02: {len(run2epi)}) - skipping")
            nSkipped += 1
            continue

        if len(run2epi) != len(run1epi):
            print(f"{subj} ses-{ses}: echo count differs between runs "
                  f"(run-01: {len(run1epi)}, run-02: {len(run2epi)}) - skipping")
            nSkipped += 1
            continue

        # Echo times in ms, read straight out of the BIDS sidecars.
        echoTimes = []
        for jsonPath in sorted(glob.glob(f"{sesDir}/func_task-{task}_run-01*ap_e?.json")):
            with open(jsonPath) as fh:
                echoTimeSec = json.load(fh)["EchoTime"]
            echoTimeMs = f"{round(echoTimeSec * 1000, 4):g}"
            print(f"  {os.path.basename(jsonPath)}: {echoTimeMs} ms")
            echoTimes.append(echoTimeMs)

        if len(echoTimes) != len(run1epi):
            print(f"{subj} ses-{ses}: {len(echoTimes)} echo times for "
                  f"{len(run1epi)} echoes - skipping")
            nSkipped += 1
            continue

        if dryRun:
            print(f"{subj} ses-{ses}: would generate job script")
            nGenerated += 1
            continue

        # --------------------------------------------------------- job script
        os.makedirs(codeDir, exist_ok=True)

        # Use the logger to initialize the file.
        logger = slurmScriptLogger(
            scriptId, slurmScriptDir,
            cpus_per_task=jobs,
            mem=memPerJob,
            time=timePerJob,
            job_name=scriptId,
            file_prefix=None,
            file_suffix=".job",
            description="Multi-echo resting-state afni_proc.py preprocessing",
        )

        # The afni_proc.py call as one backslash-continued string. Every path is
        # absolute, so the emitted script needs no shell variables of its own.
        opts = [
            "afni_proc.py",
            f"-script {codeDir}/{scriptId}.proc.csh",
            "-scr_overwrite",
            f"-subj_id {subjId}",
            f"-out_dir {outDir}",
            "-blocks despike tshift align tlrc volreg mask combine blur scale regress",
            "-radial_correlate_blocks tcat volreg",
            "-anat_has_skull yes",
            f"-tcat_remove_first_trs {firstTRs}",
            "-align_opts_aea -cost lpc+ZZ -giant_move -check_flip",
            f"-tlrc_base {tlrcBase}",
            "-tlrc_NL_warp",
            f"-copy_anat {t1Vec[0]}",
            "-volreg_align_to MIN_OUTLIER",
            "-volreg_align_e2a",
            "-volreg_tlrc_warp",
            "-mask_epi_anat yes",
            f"-dsets_me_run {' '.join(run1epi)}",
            f"-dsets_me_run {' '.join(run2epi)}",
            f"-echo_times {' '.join(echoTimes)}",
            "-combine_method m_tedana",
            "-reg_echo 2",
            "-blur_in_mask yes",
            "-blur_size 4",
            "-mask_segment_anat yes",
            "-mask_segment_erode yes",
            "-regress_motion_per_run",
            "-regress_apply_mot_types demean deriv",
            "-regress_ROI_PC WMe 1",
            "-regress_ROI_PC CSFe 1",
            "-regress_ROI_PC brain 1",
            "-regress_censor_motion 0.3",
            "-regress_censor_outliers 0.15",
            "-regress_apply_mask",
            "-regress_run_clustsim no",
            "-regress_opts_3dD -GOFORIT 10",
            f"-jobs {jobs}",
            "-regress_est_blur_epits",
            "-regress_est_blur_errts",
            "-test_stim_files no",
            "-remove_preproc_files",
            "-execute",
        ]
        afniProcCmd = " \\\n    ".join(opts)

        # Add in the first things. cd to the sesDir, run the afni_proc script. some debugging code follws, then make the output dir we care about, copy things over, delete the unwanted thing.
        logger.append(f"""module unload python
module load python/anaconda/3.9.2

cd {sesDir}

{afniProcCmd}

aprc_status=$?

# Bail out before the cleanup if the run failed, so the working
# directory survives for inspection.
if [ $aprc_status -ne 0 ]; then
    echo "ERROR: afni_proc.py returned $aprc_status for {subj} ses-{ses}"
    echo "       leaving {outDir} in place"
    exit 1
fi

mkdir -p {meDir}
mv {outDir}/*errts* {meDir}
mv {outDir}/*stats* {meDir}
mv {outDir}/*QC* {meDir}
mv {outDir}/final_epi_vr_base_min_outlier* {meDir}
mv {outDir}/anat_final.{subjId}+tlrc* {meDir}
mv {outDir}/out.ss*.txt {meDir}

if [ -f {doneFile} ]; then
    rm -rf {outDir}
else
    echo "ERROR: {doneFile} missing after the run for {subj} ses-{ses}"
    echo "       leaving {outDir} in place"
    exit 1
fi
""")

        print(f"{subj} ses-{ses}: wrote {logger.script_path}")
        nGenerated += 1

        # ------------------------------------------------------------- submit
        if submit:
            # Throttle like f06: wait while too many of our jobs are queued.
            # -h drops squeue's header line, so this counts jobs only.
            while True:
                queue = subprocess.run(["squeue", "--me", "-h"], capture_output=True,
                                       text=True, check=True).stdout
                numJobs = len(queue.splitlines())
                if numJobs <= maxJobs:
                    break
                print(f"waiting for other jobs to finish ({numJobs} queued)")
                time.sleep(waitSec)

            # Resources come from the script's #SBATCH header; only the
            # output/error files are set here, named the way f06 names them.
            # sbatch won't create the log dir, so make it before submitting.
            os.makedirs(slurmLogDir, exist_ok=True)
            os.chmod(logger.script_path, 0o777)
            subprocess.run(["sbatch",
                            f"--output={slurmLogDir}/{scriptId}.job.o",
                            f"--error={slurmLogDir}/{scriptId}.job.e",
                            logger.script_path], check=True)
            nSubmitted += 1


print(f"\nGenerated {nGenerated} job script(s) in {slurmScriptDir}")
print(f"  {nDone} subject/session(s) already processed")
print(f"  {nSkipped} subject/session(s) skipped for missing inputs")
if submit and not dryRun:
    print(f"Submitted {nSubmitted} job(s); check them with: squeue --me")
    if nSubmitted:
        print(f"Job .o/.e files will be in {slurmLogDir}")
else:
    print("\nNext steps:")
    print(f"  1. in slurmBatch.py, point slurm_dir at {slurmScriptDir} and set mode='individual'")
    print("  2. python slurmBatch.py")
    print("  3. bash submit_all_jobs.sh")
