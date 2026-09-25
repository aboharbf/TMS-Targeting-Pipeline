#!/bin/tcsh

# V3: same pipeline as V2, with names and paths matching
# serverFunctions/preprocScript.py (utils.preprocNames):
#   job script  {scriptId}.job.sh      (slurmdir)
#   job logs    {scriptId}.job.o/.e    (slurmlogdir)
#   proc script {scriptId}.proc.csh    (codedir)
#   temp dir    {baseId}.delete        (sesdir)
#   results dir {scriptId}             (sesdir)
# where
#   baseId   = {subject}_{session}_task-{task}_{spaceTag}[_{runTag}]
#   scriptId = {baseId}.{seqType}
#   subjId   = {subject}_{session}     (afni_proc -subj_id)

# ------------------------------------------------------------------ dir paths
setenv expdir `dirname $PWD`
setenv subdir ${expdir}/data
setenv SUBJECTS_DIR ${expdir}/anat

set slurmdir = ${HOME}/pipeline/slurm_preproc

# sbatch .o/.e files go in a fresh subdir per invocation of this script.
set timestamp = `date +%Y%m%d_%H%M%S`
set slurmlogdir = ${slurmdir}/logs_${timestamp}

# -------------------------------------------------------------- configuration
# Marks this pipeline run's outputs; last '_' field of the base name.
# No '_' allowed (use '-'), so names split cleanly. "" = no tag.
set runTag = noclean

set task = rest
set seqType = me                    # first '.' field after the base name; also the results dir suffix

set jobs = 8                       # -jobs for 3dDeconvolve, and --cpus-per-task
set memPerCpu = 8                  # GB per CPU
@ memPerJob = $memPerCpu * $jobs    # TOTAL memory in GB (64 at 8 jobs)
set timePerJob = 24:00:00

set tlrcBase = MNI152_2009_template.nii.gz
set firstTRs = 4

set dryRun = 0                      # 1 = report only, make sure all the req'd files are present.
set submit = 1                      # 1 = sbatch each script as it's written, 0 = write only.
set maxjobs = 200                   # Wait while more than this many of your jobs are queued.
set waitSec = 60                    # How long to sleep between queue checks.

# Space tag from the template (utils.spaceTagFromTemplate).
if ( `basename ${tlrcBase}` == MNI152_2009_template.nii.gz ) then
    set spaceTag = mni
else
    echo "ERROR: no space tag defined for tlrcBase '${tlrcBase}'"
    exit 1
endif

if ( "$runTag" =~ *_* ) then
    echo "ERROR: runTag '${runTag}' must not contain '_'"
    exit 1
endif
if ( "$runTag" == "" ) then
    set tagSfx = ""
else
    set tagSfx = "_${runTag}"
endif

# ------------------------------------------------------------------- subjects
if ( $#argv == 0 ) then
    echo "No subject specified as argument - running all subjects"
    set subs = (`ls ${subdir} | sort -n`)
else
    set subs = ($argv)
endif
echo "Preparing scripts on following subjects: $subs"
echo "Total subject count: $#subs"

mkdir -p ${slurmdir}

set nGenerated = 0
set nSubmitted = 0
set nDone = 0
set nSkipped = 0

foreach subject ($subs)
foreach ses (01 02 03 04)

    set session = ses-${ses}
    set sesdir  = ${subdir}/${subject}/${session}

    # Names
    set baseId   = ${subject}_${session}_task-${task}_${spaceTag}${tagSfx}
    set scriptId = ${baseId}.${seqType}     # Stem of the job script, logs, proc script, job name.
    set subjId   = ${subject}_${session}    # afni_proc -subj_id; names the files inside the results dir.

    # Script outputs
    set codedir = ${subdir}/${subject}/code     # Where the afni proc script ends up.
    set jobfile = ${slurmdir}/${scriptId}.job.sh

    # Afni_proc outputs
    set outdir   = ${sesdir}/${baseId}.delete                # Temporary dir, files moved, ends up deleted.
    set medir    = ${sesdir}/${scriptId}                     # Where the useful things end up.
    set donefile = ${medir}/out.ss_review.${subjId}.txt      # Evidence of completion.

    if ( ! -d ${sesdir} ) then
        echo "${subject} ${session}: no session directory - skipping"
        @ nSkipped++
        continue
    endif
    cd ${sesdir}

    if ( -e ${donefile} ) then
        echo "${subject} ${session}: already processed - skipping"
        @ nDone++
        continue
    endif

    set t1 = (`ls ${subdir}/${subject}/anat/${subject}_T1fs_conform.nii* | head -n1`)
    if ( $#t1 == 0 ) then
        echo "${subject}: no T1 found - skipping ${session}"
        @ nSkipped++
        continue
    endif

    set run1epi = (`ls ${sesdir}/func_task-${task}_run-01*ap_e?.nii`)
    set run2epi = (`ls ${sesdir}/func_task-${task}_run-02*ap_e?.nii`)
    if ( $#run1epi == 0 || $#run2epi == 0 ) then
        echo "${subject} ${session}: missing EPIs (run-01: $#run1epi, run-02: $#run2epi) - skipping"
        @ nSkipped++
        continue
    endif

    if ( $#run2epi != $#run1epi ) then
        echo "${subject} ${session}: echo count differs between runs (run-01: $#run1epi, run-02: $#run2epi) - skipping"
        @ nSkipped++
        continue
    endif

    # Echo times in ms, collected in the same ls order as the datasets above.
    set e = ()
    foreach echotimefname (`ls ${sesdir}/func_task-${task}_run-01*ap_e?.json`)
        set echotimesec = `grep '"EchoTime"' ${echotimefname} | cut -d: -f2 | tr -d ' ,'`
        set echotime = `echo "1000 ${echotimesec} * p" | dc`
        echo "  `basename ${echotimefname}`: ${echotime} ms"
        set e = ($e ${echotime})
    end

    if ( $#e != $#run1epi ) then
        echo "${subject} ${session}: $#e echo times for $#run1epi echoes - skipping"
        @ nSkipped++
        continue
    endif

    if ( $dryRun ) then
        echo "${subject} ${session}: would generate job script"
        @ nGenerated++
        continue
    endif

    mkdir -p ${codedir}

##### start of here file
cat > ${jobfile} <<JobFileContents
#!/bin/tcsh
#SBATCH --job-name=${scriptId}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=${jobs}
#SBATCH --time=${timePerJob}
#SBATCH --mem=${memPerJob}G
## Script Generated: `date '+%Y-%m-%d %H:%M:%S'`
## Script ID: ${scriptId}
## Description: Multi-echo resting-state afni_proc.py preprocessing

module unload python
module load python/anaconda/3.9.2

cd ${sesdir}

afni_proc.py \
    -script ${codedir}/${scriptId}.proc.csh \
    -scr_overwrite \
    -subj_id ${subjId} \
    -out_dir ${outdir} \
    -blocks despike tshift align tlrc volreg mask combine blur scale regress \
    -radial_correlate_blocks tcat volreg \
    -anat_has_skull yes \
    -tcat_remove_first_trs ${firstTRs} \
    -align_opts_aea -cost lpc+ZZ -giant_move -check_flip \
    -tlrc_base ${tlrcBase} \
    -tlrc_NL_warp \
    -copy_anat ${t1} \
    -volreg_align_to MIN_OUTLIER \
    -volreg_align_e2a \
    -volreg_tlrc_warp \
    -mask_epi_anat yes \
    -dsets_me_run ${run1epi} \
    -dsets_me_run ${run2epi} \
    -echo_times ${e} \
    -combine_method m_tedana \
    -reg_echo 2 \
    -blur_in_mask yes \
    -blur_size 4 \
    -mask_segment_anat yes \
    -mask_segment_erode yes \
    -regress_motion_per_run \
    -regress_apply_mot_types demean deriv \
    -regress_ROI_PC WMe 1 \
    -regress_ROI_PC CSFe 1 \
    -regress_ROI_PC brain 1 \
    -regress_censor_motion 0.3 \
    -regress_censor_outliers 0.15 \
    -regress_apply_mask \
    -regress_run_clustsim no \
    -regress_opts_3dD -GOFORIT 10 \
    -jobs ${jobs} \
    -regress_est_blur_epits \
    -regress_est_blur_errts \
    -test_stim_files no \
    -remove_preproc_files \
    -execute

set aprc_status = \$status

# Bail out before the cleanup if the run failed, so the working
# directory survives for inspection.
if ( \$aprc_status != 0 ) then
    echo "ERROR: afni_proc.py returned \$aprc_status for ${subject} ${session}"
    echo "       leaving ${outdir} in place"
    exit 1
endif

# Some of these patterns can legitimately match nothing (e.g. *stats*
# when the regress block uses 3dTproject); nonomatch keeps that non-fatal.
set nonomatch

mkdir -p ${medir}
mv ${outdir}/*errts* ${medir}
mv ${outdir}/*stats* ${medir}
mv ${outdir}/*QC* ${medir}
mv ${outdir}/final_epi_vr_base_min_outlier* ${medir}
mv ${outdir}/anat_final.${subjId}+tlrc* ${medir}
mv ${outdir}/out.ss*.txt ${medir}

if ( -e ${donefile} ) then
    rm -rf ${outdir}
else
    echo "ERROR: ${donefile} missing after the run for ${subject} ${session}"
    echo "       leaving ${outdir} in place"
    exit 1
endif

JobFileContents
##### end of here file

    echo "${subject} ${session}: wrote ${jobfile}"
    @ nGenerated++

    if ( $submit ) then
        # Throttle: wait while too many of our jobs are queued.
        set numjobs = `squeue --me --noheader | wc -l`
        while ( $numjobs > $maxjobs )
            echo "waiting for other jobs to finish ($numjobs queued)"
            sleep $waitSec
            set numjobs = `squeue --me --noheader | wc -l`
        end

        # Resources come from the job file's #SBATCH header; only the
        # output/error files are set here. sbatch won't create the log dir.
        mkdir -p ${slurmlogdir}
        chmod a+rwx ${jobfile}
        sbatch \
            --output=${slurmlogdir}/${scriptId}.job.o \
            --error=${slurmlogdir}/${scriptId}.job.e \
            ${jobfile}
        @ nSubmitted++
    endif

end
end

echo ""
echo "Generated ${nGenerated} job script(s) in ${slurmdir}"
echo "  ${nDone} subject/session(s) already processed"
echo "  ${nSkipped} subject/session(s) skipped for missing inputs"
if ( $submit && ! $dryRun ) then
    echo "Submitted ${nSubmitted} job(s); check them with: squeue --me"
    if ( $nSubmitted > 0 ) echo "Job .o/.e files will be in ${slurmlogdir}"
endif
