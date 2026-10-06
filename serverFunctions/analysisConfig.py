"""
Analysis settings shared by preprocScript.py, paramScript.py, peakScript.py and
fileCheck.py. Settings only, no logic: anything that defines the data, or must
agree between scripts, lives here. Per-script switches (dryRun, submit, maxJobs,
scriptMode, ...) stay in each script.

Each script calls utils.snapshotConfig() at start-up, which copies this exact
file next to that run's session log (~/pipeline/scripts/logs/) and logs its
sha256, so every run records the settings it used.
"""

from pathlib import Path

# ------------------------------------------------------------------ dir paths
projDir = Path("~").expanduser()
dataDir = f'{projDir}/nbthetaconn/data'                             # Inputs (T1, EPIs, sidecars); read only.
outputDir = f'{projDir}/nbthetaconn/analysis_out/pipeline_params'    # Preprocessing outputs; mirrors dataDir as {subj}/ses-{ses}, {subj}/code.
maskDir = f'{projDir}/nbthetaconn/masks'
resultsDir = f'{projDir}/pipeline/results'                          # peakScript outputs, one subdir per subject.

# ------------------------------------------------------------- shared naming
# Names are built by utils.preprocNames from these.
runTag = 'param'                        # Base run tag; last '_' field of the base name.
                                        # No '_' allowed (use '-'). '' = no tag.
task = 'rest'
seqTypeVec = ['me']                     # first '.' field after the base name; also the results dir suffix
sesVec = ['01', '02', '03', '04']       # assume all subjects have 4 sessions
tlrcBase = 'MNI152_2009_template.nii.gz'

# ------------------------------------------- preprocessing vs. parameter grid
# Base run (preprocScript.py -> afni_proc.py). These define what runTag means:
# changing any of them needs a new runTag, or the old name describes new data.
# Strings, as written into the afni_proc command.
preprocBlur = '4'                       # -blur_size
preprocCensorMotion = '0.3'             # -regress_censor_motion
preprocCensorOutliers = '0.15'          # -regress_censor_outliers; the grid inherits this one
firstTRs = 4                            # -tcat_remove_first_trs

# Grid (paramScript.py -> x07.blur_censor_param.csh), rebuilt from the base run.
# Strings, written exactly as they should appear in the names ('4', not 4.0),
# since x07 builds the same names from the same text.
# fwhm '4' x motion '0.3' repeats the base run's settings: a check on x07.
fwhmVec = ['0', '2', '4', '6']          # 3dBlurInMask -FWHM; '0' = no blur
motVec = ['0', '0.15', '0.3', '0.45']   # 1d_tool.py -censor_motion limit

# ---------------------------------------------------------------- peak search
# peakScript.py. '{}' is filled with each entry of the list below it.
sgaccMaskTemplate = f"{maskDir}/subgenual_{{}}_mask.nii"
maskTypeVec = ['seed', 'network']       # Anatomical vs. network based sgACC activity.
clustMaskTemplate = f"{maskDir}/Parcels_MNI_222.resam.ldlpfc.neurosynth.{{}}.nii"
clustMaskVec = ['orig', 'dilate_5', 'erode_1']

# ------------------------------------------------------------ SLURM resources
# Per job. Memory is the TOTAL for the job, not per CPU.
preprocCpus = 8                         # --cpus-per-task, and afni_proc -jobs for 3dDeconvolve
preprocMem = '64G'                      # 8G per CPU, as f06
preprocTime = '24:00:00'

paramCpus = 2                           # --cpus-per-task and OMP_NUM_THREADS
paramMem = '16G'                        # 3dpc holds both runs at once
paramTime = '04:00:00'                  # whole grid for one subject-session
