import os
import glob
import json
from pathlib import Path

from utils import slurmScriptLogger

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = f'{projDir}/nbthetaconn/data'

slurmScriptDir = f'{projDir}/pipeline/slurm_preproc'

# -------------------------------------------------------------- configuration
task = 'rest'
seqType = 'me'                          # names the results dir and the job file
sesVec = ['01', '02', '03', '04']       # assume all subjects have 4 sessions

jobs = 16                               # -jobs for 3dDeconvolve, and --cpus-per-task
memPerJob = '16G'                       # TOTAL memory. 
timePerJob = '24:00:00'

tlrcBase = 'MNI152_2009_template.nii.gz'
firstTRs = 4

dryRun = False                          # True = report only, write nothing


def posixGlob(pattern):
    """
    sorted(glob.glob(...)) with separators normalised. sorted() reproduces the
    ordering `ls` gave the csh, which matters because the echo times must line
    up with the echo datasets. The separator fix only bites if the generator is
    run from Windows for a dry run; on the server the paths are POSIX already.
    """
    return [path.replace(os.sep, '/') for path in sorted(glob.glob(pattern))]


# ------------------------------------------------------------------- subjects
subjVec = [item for item in os.listdir(dataDir)
           if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# As a test, just do the first few
# subjVec = subjVec[0:3]

print(f"Preparing scripts on following subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}")


def buildAfniProcCmd(subj, ses, codeDir, outDir, t1, run1epi, run2epi, echoTimes):
    """
    Assemble the afni_proc.py call for one subject/session as a single
    backslash-continued string. Every path is absolute, so the emitted script
    needs no shell variables of its own.
    """
    opts = [
        "afni_proc.py",
        f"-script {codeDir}/proc.{subj}.ses-{ses}.{task}.csh",
        "-scr_overwrite",
        f"-subj_id {subj}",
        f"-out_dir {outDir}",
        "-blocks despike tshift align tlrc volreg mask combine blur scale regress",
        "-radial_correlate_blocks tcat volreg",
        "-anat_has_skull yes",
        f"-tcat_remove_first_trs {firstTRs}",
        "-align_opts_aea -cost lpc+ZZ -giant_move -check_flip",
        f"-tlrc_base {tlrcBase}",
        "-tlrc_NL_warp",
        f"-copy_anat {t1}",
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
    return " \\\n    ".join(opts)


nGenerated = 0
nDone = 0
nSkipped = 0

for subj in subjVec:
    for ses in sesVec:

        sesDir = f"{dataDir}/{subj}/ses-{ses}"
        codeDir = f"{dataDir}/{subj}/code"

        
        outDir = f"{sesDir}/{subj}.results.task-{task}-mni.delete" # Temporary, gets deleted once the keepers have been moved out.
        meDir = f"{sesDir}/{subj}.results.task-{task}-mni.{seqType}" # Where the useful things end up.
        doneFile = f"{meDir}/out.ss_review.{subj}.txt"         # Evidence of completion.

        if not os.path.isdir(sesDir):
            print(f"{subj} ses-{ses}: no session directory - skipping")
            nSkipped += 1
            continue

        if os.path.exists(doneFile):
            print(f"{subj} ses-{ses}: already processed - skipping")
            nDone += 1
            continue

        t1Vec = posixGlob(f"{dataDir}/{subj}/anat/{subj}_T1fs_conform.nii*")
        if not t1Vec:
            print(f"{subj}: no T1 found - skipping ses-{ses}")
            nSkipped += 1
            continue

        run1epi = posixGlob(f"{sesDir}/func_task-{task}_run-01*ap_e?.nii")
        run2epi = posixGlob(f"{sesDir}/func_task-{task}_run-02*ap_e?.nii")
        if not run1epi or not run2epi:
            print(f"{subj} ses-{ses}: missing EPIs "
                  f"(run-01: {len(run1epi)}, run-02: {len(run2epi)}) - skipping")
            nSkipped += 1
            continue

        # Echo times in ms, read straight out of the BIDS sidecars.
        echoTimes = []
        for jsonPath in posixGlob(f"{sesDir}/func_task-{task}_run-01*ap_e?.json"):
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

        logger = slurmScriptLogger(
            subj, ses, task, seqType, slurmScriptDir,
            cpus_per_task=jobs,
            mem=memPerJob,
            time=timePerJob,
            job_prefix="prep",
            file_prefix="preproc_job",
            description="Multi-echo resting-state afni_proc.py preprocessing",
        )

        afniProcCmd = buildAfniProcCmd(subj, ses, codeDir, outDir,
                                       t1Vec[0], run1epi, run2epi, echoTimes)

        # The whole job body in one go, mirroring the here file in the csh.
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
mv {outDir}/anat_final.{subj}+tlrc* {meDir}
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


print(f"\nGenerated {nGenerated} job script(s) in {slurmScriptDir}")
print(f"  {nDone} subject/session(s) already processed")
print(f"  {nSkipped} subject/session(s) skipped for missing inputs")
print("\nNext steps:")
print(f"  1. point slurm_dir in slurmBatch.py at {slurmScriptDir}, and raise its")
print(f"     time/memory/cpus_per_task to match ({timePerJob}, {memPerJob}, {jobs})")
print("  2. python slurmBatch.py")
print("  3. sbatch run_all_jobs.sh")
