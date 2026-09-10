#!/bin/tcsh

setenv expdir `dirname $PWD`
setenv subdir ${expdir}/data
setenv scrdir ${expdir}/SCRIPTS
setenv stmdir ${expdir}/stimtimes
setenv resdir ${expdir}/results
setenv SUBJECTS_DIR ${expdir}/anat
setenv outfile f06.afni_proc_rest.csh
setenv jobs 16

if ( "$argv" == "" ) then
        echo "No subject specified as argument - running all subjects"
setenv subs `ls ${subdir}`
else
echo subs = $argv
setenv subs $argv
endif


foreach subject ($subs)
cd ${subdir}/${subject}
foreach session (ses-01 ses-02 ses-03 ses-04)
cd ${subdir}/${subject}/${session}


setenv logdir ${subdir}/${subject}/code
setenv logfile ${logdir}/log.${outfile}.${subject}.${session}

#if (-e ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me/stats.REML_cmd) then
if (-e $logfile) then
        echo "this script has been run for subject $subject"
else
echo "#$subject $session $outfile failed" >> ${logfile}
setenv t1 `ls ${subdir}/${subject}/anat/${subject}_T1fs_conform.nii* | head -n1`

setenv run1epi `ls func_task-rest_run-01*ap_e?.nii`
setenv run2epi `ls func_task-rest_run-02*ap_e?.nii`


set e=""
set d=""
foreach echotimefname ( `ls func_task-rest_run-01*ap_e?.json` )

set echotimesec=`cat ${echotimefname} | grep EchoTime | cut -d: -f2 | tr ',' ' ' | tr -s ' '`
set echotime=`echo "1000 ${echotimesec} * p" | dc`
set fname=`basename ${echotimefname} .json`.nii
echo $echotime
echo "$fname"
set d=($d ${fname})
set e=($e ${echotime})
echo "$e"

end



#####start of here file
cat > ${logfile} <<End-of-message-fool
#!/bin/tcsh

module unload python
module load python/anaconda/3.9.2


cd ${subdir}/${subject}/${session}


afni_proc.py \
-script ${subdir}/${subject}/code/proc.${subject}.${session}.rest.csh \
-scr_overwrite \
-subj_id ${subject} \
-out_dir ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete \
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

mkdir ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/*errts* ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/*stats* ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/*QC* ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/final_epi_vr_base_min_outlier* ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/anat_final.${subject}+tlrc* ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me
mv ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete/out.ss*.txt ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.me

rm -rf ${subdir}/${subject}/${session}/${subject}.results.task-rest-mni.delete

#####end of here file
End-of-message-fool

setenv maxjobs 200
setenv numjobs `squeue --me | wc -l`
while ($numjobs > $maxjobs)
echo "waiting for other jobs to finish"
setenv numjobs `squeue --me | wc -l`
sleep 60
end

chmod a+rwx ${logfile}
sbatch \
--nodes=1 \
--ntasks=1 \
--cpus-per-task=${jobs} \
--mem-per-cpu=16G \
--output=${scrdir}/${subject}.${session}.f06.afni_proc.o \
--error=${scrdir}/${subject}.${session}.f06.afni_proc.e \
${logfile}

else
        echo "run $infile"
endif
endif
end
end