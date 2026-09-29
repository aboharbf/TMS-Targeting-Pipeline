#!/bin/bash
#SBATCH --job-name=001_ses-04_task-rest_mni_noclean.me
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
## Script Generated: 2026-09-28 10:01:26
## Script ID: 001_ses-04_task-rest_mni_noclean.me
## Description: Multi-echo resting-state afni_proc.py preprocessing
## Author: Farid Aboharb, Balderston Lab

module unload python
module load python/anaconda/3.9.2

cd /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04

afni_proc.py \
    -script /cbica/projects/nbthetaconn/nbthetaconn/data/001/code/001_ses-04_task-rest_mni_noclean.me.proc.csh \
    -scr_overwrite \
    -subj_id 001_ses-04 \
    -out_dir /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete \
    -blocks despike tshift align tlrc volreg mask combine blur scale regress \
    -radial_correlate_blocks tcat volreg \
    -anat_has_skull yes \
    -tcat_remove_first_trs 4 \
    -align_opts_aea -cost lpc+ZZ -giant_move -check_flip \
    -tlrc_base MNI152_2009_template.nii.gz \
    -tlrc_NL_warp \
    -copy_anat /cbica/projects/nbthetaconn/nbthetaconn/data/001/anat/001_T1fs_conform.nii.gz \
    -volreg_align_to MIN_OUTLIER \
    -volreg_align_e2a \
    -volreg_tlrc_warp \
    -mask_epi_anat yes \
    -dsets_me_run /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-01_MB6_TE3_bold_dir-ap_e1.nii /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-01_MB6_TE3_bold_dir-ap_e2.nii /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-01_MB6_TE3_bold_dir-ap_e3.nii \
    -dsets_me_run /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-02_MB6_TE3_bold_dir-ap_e1.nii /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-02_MB6_TE3_bold_dir-ap_e2.nii /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/func_task-rest_run-02_MB6_TE3_bold_dir-ap_e3.nii \
    -echo_times 13.4 31.12 48.84 \
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
    -jobs 8 \
    -regress_est_blur_epits \
    -regress_est_blur_errts \
    -test_stim_files no

aprc_status=$?

# Bail out before the cleanup if the run failed, so the working
# directory survives for inspection.
if [ $aprc_status -ne 0 ]; then
    echo "ERROR: afni_proc.py returned $aprc_status for 001 ses-04"
    echo "       leaving /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete in place"
    exit 1
fi

mkdir -p /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/*errts* /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/*stats* /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/*QC* /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/final_epi_vr_base_min_outlier* /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/anat_final.001_ses-04+tlrc* /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me
mv /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete/out.ss*.txt /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me

if [ -f /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me/out.ss_review.001_ses-04.txt ]; then
    rm -rf /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete
else
    echo "ERROR: /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.me/out.ss_review.001_ses-04.txt missing after the run for 001 ses-04"
    echo "       leaving /cbica/projects/nbthetaconn/nbthetaconn/data/001/ses-04/001_ses-04_task-rest_mni_noclean.delete in place"
    exit 1
fi

