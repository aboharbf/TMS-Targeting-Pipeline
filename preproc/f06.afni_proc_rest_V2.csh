 setenv expdir `dirname $PWD`
setenv subdir ${expdir}/data
setenv scrdir ${expdir}/SCRIPTS
setenv stmdir ${expdir}/stimtimes
setenv resdir ${expdir}/results
setenv SUBJECTS_DIR ${expdir}/anat
setenv outfile f06.afni_proc_rest.csh
setenv jobs 8
setenv memPerCpu 8

# Marks this pipeline run's outputs; goes before the final dot of script/log
# names and before .delete/.me in dir names. Set to "" for no tag.
setenv runTag no_clean
if ( "$runTag" == "" ) then
    set tagSfx = ""
else
    set tagSfx = "_${runTag}"
endif

# sbatch writes its .o/.e files here, so this has to exist before we submit
mkdir -p ${scrdir}

if ( $#argv == 0 ) then
    echo "No subject specified as argument - running all subjects"
    set subs = (`ls ${subdir}`)
else
    set subs = ($argv)
endif
echo "subs = $subs"


foreach subject ($subs)
foreach session (ses-01 ses-02 ses-03 ses-04)

    if ( ! -d ${subdir}/${subject}/${session} ) then
        echo "${subject}: no ${session} - skipping"
        continue
    endif
    cd ${subdir}/${subject}/${session}

    set logdir  = ${subdir}/${subject}/code
    set jobfile = ${logdir}/job.${outfile}.${subject}.${session}${tagSfx}

    set outdir  = ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni${tagSfx}.delete     # Temporary, gets deleted.
    set medir   = ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni${tagSfx}.me     # Where the useful things are placed.

    # evidence of completion
    set donefile = ${medir}/out.ss_review.${subject}.txt

    mkdir -p ${logdir}

    if ( -e ${donefile} ) then
        echo "${subject} ${session}: already processed - skipping"
        continue
    endif

    set t1 = (`ls ${subdir}/${subject}/anat/${subject}_T1fs_conform.nii* | head -n1`)
    if ( $#t1 == 0 ) then
        echo "${subject}: no T1 found - skipping ${session}"
        continue
    endif

    set run1epi = (`ls func_task-rest_run-01*ap_e?.nii`)
    set run2epi = (`ls func_task-rest_run-02*ap_e?.nii`)
    if ( $#run1epi == 0 || $#run2epi == 0 ) then
        echo "${subject} ${session}: missing EPIs (run-01: $#run1epi, run-02: $#run2epi) - skipping"
        continue
    endif

    if ( $#run2epi != $#run1epi ) then
        echo "${subject} ${session}: echo count differs between runs (run-01: $#run1epi, run-02: $#run2epi) - skipping"
        continue
    endif

    # Echo times in ms, collected in the same ls order as the datasets above.
    set e = ()
    foreach echotimefname (`ls func_task-rest_run-01*ap_e?.json`)
        set echotimesec = `grep '"EchoTime"' ${echotimefname} | cut -d: -f2 | tr -d ' ,'`
        set echotime = `echo "1000 ${echotimesec} * p" | dc`
        echo "${echotimefname}: ${echotime} ms"
        set e = ($e ${echotime})
    end

    if ( $#e != $#run1epi ) then
        echo "${subject} ${session}: $#e echo times for $#run1epi echoes - skipping"
        continue
    endif


##### start of here file
cat > ${jobfile} <<JobFileContents
#!/bin/tcsh

module unload python
module load python/anaconda/3.9.2

cd ${subdir}/${subject}/${session}

set outdir = ${outdir}
set medir  = ${medir}

afni_proc.py \
-script ${logdir}/proc.${subject}.${session}.rest${tagSfx}.csh \
-scr_overwrite \
-subj_id ${subject} \
-out_dir \$outdir \
-blocks despike tshift align tlrc volreg mask combine blur scale regress \
-radial_correlate_blocks tcat volreg \
-anat_has_skull yes \
-tcat_remove_first_trs 4 \
-align_opts_aea -cost lpc+ZZ -giant_move -check_flip \
-tlrc_base MNI152_2009_template.nii.gz \
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
    echo "       leaving \$outdir in place"
    exit 1
endif

# Some of these patterns can legitimately match nothing (e.g. *stats*
# when the regress block uses 3dTproject); nonomatch keeps that non-fatal.
set nonomatch

mkdir -p \$medir
mv \$outdir/*errts* \$medir
mv \$outdir/*stats* \$medir
mv \$outdir/*QC* \$medir
mv \$outdir/final_epi_vr_base_min_outlier* \$medir
mv \$outdir/anat_final.${subject}+tlrc* \$medir
mv \$outdir/out.ss*.txt \$medir

if ( -e ${donefile} ) then
    rm -rf \$outdir
else
    echo "ERROR: ${donefile} missing after the run for ${subject} ${session}"
    echo "       leaving \$outdir in place"
    exit 1
endif

JobFileContents
##### end of here file


    # Throttle: don't flood the queue.
    set maxjobs = 200
    set numjobs = `squeue --me --noheader | wc -l`
    while ( $numjobs >= $maxjobs )
        echo "waiting for other jobs to finish ($numjobs queued)"
        sleep 60
        set numjobs = `squeue --me --noheader | wc -l`
    end

    chmod a+rx ${jobfile}
    sbatch \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=${jobs} \
    --mem-per-cpu=16G \
    --output=${scrdir}/${subject}.${session}.f06.afni_proc${tagSfx}.o \
    --error=${scrdir}/${subject}.${session}.f06.afni_proc${tagSfx}.e \
    ${jobfile}

end
end
