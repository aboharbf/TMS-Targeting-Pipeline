#!/bin/tcsh -xef

# x07: rerun blur / scale / censor / regress from a finished afni_proc
# results dir, over a grid of blur sizes x motion censor limits.
# DRAFT - not yet run.
#
# Mirrors lines 405-543 of the afni_proc proc script (blur through the
# 3dTproject errts). Everything upstream (tcat -> tedana combine) is reused
# from the base run, which must have been run without -remove_preproc_files
# and with pb04, the masks and the 1D files moved into the results dir.
#
# usage:
#   tcsh -xef f07.rest_post_temp.csh <resdir> "<fwhm list>" "<motion limit list>"
#   e.g.
#   tcsh -xef f07.rest_post_temp.csh \
#       /path/001/ses-01/001_ses-01_task-rest_mni_param.me "0 4 6" "0.2 0.3 0.5"
#
# Branch structure (each piece runs only as often as its inputs change):
#   censor branch   once per motion limit      censor -> detrend -> 3dpc -> X matrix
#   blur branch     once per FWHM              blur -> scale  (from unblurred pb04)
#   merge           once per FWHM x motion     3dTproject -> errts
#
# Outputs: one results dir per combination, next to the base one, named so
# utils.preprocNames / resolveErrts find it with runTag = <baseTag>-<varTag>:
#   base     {baseId}.{seqType}                 e.g. ..._mni_param.me
#   variant  {baseId}-b{F}m{M}.{seqType}        e.g. ..._mni_param-b4m0p3.me
# '.' in a value becomes 'p' (0.3 -> 0p3), since '.' separates name fields.
# If the base run is untagged, the variant tag is joined with '_' instead.
# Each variant dir holds errts.{subjId}.tproject+tlrc plus the small 1D
# files (censor, ROI PCs, X matrices) that produced it.
#
# Intermediates go in {resdir}/post/. Rerunning skips finished work:
#   censor branch  done when post/mot{M}/X.nocensor.xmat.1D exists
#   merge          done when the variant errts .HEAD exists
#
# Validation: the variant with FWHM 4 / motion 0.3 should reproduce the base
# run's errts. Compare (from the variant dir):
#   3dcalc -a errts.{subjId}.tproject+tlrc -b {resdir}/errts.{subjId}.tproject+tlrc \
#          -expr 'a-b' -prefix rm.diff
#   3dBrickStat -absolute -max rm.diff+tlrc       # expect ~0 (float rounding)
#   diff X.xmat.1D {resdir}/X.xmat.1D             # expect no differences

# -------------------------------------------------------------- configuration
set keepPb06 = 0        # 1 = keep each FWHM's blurred/scaled data after its errts are done

# ------------------------------------------------------------------ arguments
if ( $#argv != 3 ) then
    echo "usage: tcsh -xef f07.rest_post_temp.csh <resdir> <fwhm list> <motion limit list>"
    exit 1
endif

set resdir = `realpath $argv[1]`
set fwhms  = ( $argv[2] )
set mots   = ( $argv[3] )

# Names, from the base results dir {baseId}.{seqType}
set resname = `basename $resdir`
set baseId  = $resname:r
set seqType = $resname:e
set sesdir  = `dirname $resdir`
set subj    = `echo $baseId | cut -d_ -f1-2`            # {subject}_{session}, afni_proc -subj_id

# {subj}_ses-{ses}_task-{task}_{space} has 4 '_' fields; a 5th is the run tag.
if ( `echo $baseId | awk -F_ '{print NF}'` > 4 ) then
    set tagSep = '-'        # extend the base run tag: param -> param-b4m0p3
else
    set tagSep = '_'        # untagged base: the variant tag becomes the run tag
endif

cd $resdir

# ------------------------------------------------------------- input checks
set runs  = (`count_afni -digits 2 1 2`)
set nruns = $#runs
set mask  = $resdir/mask_epi_anat.$subj+tlrc

set missing = ()
foreach f ( mask_epi_anat.$subj+tlrc.HEAD mask_WMe_resam+tlrc.HEAD \
            mask_CSFe_resam+tlrc.HEAD dfile_rall.1D outcount_${subj}_censor.1D )
    if ( ! -f $f ) set missing = ( $missing $f )
end
foreach run ( $runs )
    if ( ! -f pb04.$subj.r$run.combine+tlrc.HEAD ) set missing = ( $missing pb04.$subj.r$run.combine+tlrc.HEAD )
end
if ( $#missing > 0 ) then
    echo "ERROR: missing inputs in ${resdir}:"
    foreach f ( $missing )
        echo "    $f"
    end
    exit 1
endif

set tr_counts = ()
foreach run ( $runs )
    set tr_counts = ( $tr_counts `3dnvals pb04.$subj.r$run.combine+tlrc` )
end

set postdir = $resdir/post
mkdir -p $postdir

# Cleanup globs (rm.*) can legitimately match nothing; keep that non-fatal under -e.
set nonomatch

# ------------------------------------------- motion regressors (fixed)
# Same for every combination, so built once. Mimics lines 425 - 439.
cd $postdir
1d_tool.py -overwrite -infile $resdir/dfile_rall.1D -set_nruns $nruns \
           -demean -write motion_demean.1D
1d_tool.py -overwrite -infile $resdir/dfile_rall.1D -set_nruns $nruns \
           -derivative -demean -write motion_deriv.1D
1d_tool.py -overwrite -infile motion_demean.1D -set_nruns $nruns \
           -split_into_pad_runs mot_demean
1d_tool.py -overwrite -infile motion_deriv.1D -set_nruns $nruns \
           -split_into_pad_runs mot_deriv

# Same -ortvec order as the proc script, so X columns line up with the base run.
# These arguments are defined in the original proc script on lines 520 - 526. Inserted into 3dDeconvolve call below.
set mot_orts = ()
foreach run ( $runs )
    set mot_orts = ( $mot_orts -ortvec $postdir/mot_demean.r$run.1D mot_demean_r$run )
end
foreach run ( $runs )
    set mot_orts = ( $mot_orts -ortvec $postdir/mot_deriv.r$run.1D mot_deriv_r$run )
end

# ===================== censor branch: once per motion limit =====================
foreach mot ( $mots )
    set mtag = m`echo $mot | sed 's/\./p/g'`
    set cdir = $postdir/$mtag

    if ( -f $cdir/X.nocensor.xmat.1D ) then
        echo "censor branch $mtag: done - skipping"
        continue
    endif

    # Start clean, so a run killed partway through doesn't leave stale files.
    rm -rf $cdir
    mkdir -p $cdir
    cd $cdir

    # create censor file motion_${subj}_censor.1D, for censoring motion
    # mimics lines 442 - 450 in the proc script
    1d_tool.py -infile $resdir/dfile_rall.1D -set_nruns $nruns \
        -show_censor_count -censor_prev_TR                     \
        -censor_motion $mot motion_${subj}

    # combine with the outlier censor from the base run
    1deval -a motion_${subj}_censor.1D -b $resdir/outcount_${subj}_censor.1D \
           -expr "a*b" > censor_${subj}_combined_2.1D

    ## Intervening Code on proc script is for quality control/uneffected by blur + censoring parameterization.

    # detrend, so principal components are not affected (Line 473)
    foreach run ( $runs )
        1d_tool.py -set_run_lengths $tr_counts -select_runs $run              \
                   -infile censor_${subj}_combined_2.1D -write rm.censor.r$run.1D

        # do not let censored time points affect detrending
        3dTproject -polort 3 -prefix rm.det_pcin_r$run                         \
                   -censor rm.censor.r$run.1D -cenmode KILL                    \
                   -input $resdir/pb04.$subj.r$run.combine+tlrc
    end

    # catenate runs, prepare to censor TRs
    3dTcat -prefix rm.det_pcin_rall rm.det_pcin_r*+tlrc.HEAD

    # make ROI PCs: WMe, CSFe, brain; zero pad censored TRs
    # mimics line 489 to 513 in proc script - as a loop over 3 items instead of 3 repeats.
    foreach roi ( WMe CSFe brain )

        if ( $roi == brain ) then
            set roimask = $mask
        else
            set roimask = $resdir/mask_${roi}_resam+tlrc
        endif

        3dpc -mask $roimask -pcsave 1 -prefix rm.ROIPC.$roi rm.det_pcin_rall+tlrc
        1d_tool.py -censor_fill_parent censor_${subj}_combined_2.1D \
            -infile rm.ROIPC.${roi}_vec.1D -write ROIPC.$roi.1D
    end

    # Design matrix only (-x1D_stop): no voxelwise fit, so -input just supplies
    # the run lengths. pb04 has the same run structure as any blurred pb06,
    # which is why this runs once per motion limit rather than per combination.
    3dDeconvolve -input $resdir/pb04.$subj.r*.combine+tlrc.HEAD  \
        -censor censor_${subj}_combined_2.1D                     \
        -ortvec ROIPC.WMe.1D ROIPC.WMe                           \
        -ortvec ROIPC.CSFe.1D ROIPC.CSFe                         \
        -ortvec ROIPC.brain.1D ROIPC.brain                       \
        $mot_orts                                                \
        -polort 3                                                \
        -num_stimts 0                                            \
        -GOFORIT 10                                              \
        -x1D X.xmat.1D                                           \
        -x1D_uncensored X.nocensor.xmat.1D                       \
        -x1D_stop

    rm -f rm.*

    # Following this line in proc, 3dTproject runs, which is influenced both by censor and blur.
    # the above censor outputs are cheap to generate and store, so are kept here and used with the blur prep in the loop below.
end

# ============ blur branch: once per FWHM, then every motion limit against it ============
foreach fwhm ( $fwhms )
    set btag = b`echo $fwhm | sed 's/\./p/g'`
    set bdir = $postdir/$btag

    # Variant dirs still missing an errts for this FWHM
    set todo = ()
    foreach mot ( $mots )
        set mtag  = m`echo $mot | sed 's/\./p/g'`
        set vdir  = $sesdir/${baseId}${tagSep}${btag}${mtag}.${seqType}
        if ( ! -f $vdir/errts.${subj}.tproject+tlrc.HEAD ) set todo = ( $todo $mot )
    end
    if ( $#todo == 0 ) then
        echo "blur branch $btag: all errts done - skipping"
        continue
    endif

    # --------------------------------------- blur + scale (pb04 -> pb06)
    mkdir -p $bdir
    cd $bdir
    foreach run ( $runs )
        if ( -f pb06.$subj.r$run.scale+tlrc.HEAD ) continue
        rm -f rm.*      # leftovers from a killed run

        # Blur the data (line 408 in proc script)
        set src = $resdir/pb04.$subj.r$run.combine+tlrc
        if ( $fwhm != 0 ) then
            3dBlurInMask -preserve -FWHM $fwhm -Mmask $mask \
                         -prefix rm.pb05.$subj.r$run.blur $src
            set src = rm.pb05.$subj.r$run.blur+tlrc
        endif

        # scale each voxel time series to have a mean of 100
        # (be sure no negatives creep in; subject to a range of [0,200])
        # Loop at 417 in proc.
        3dTstat -prefix rm.mean_r$run $src
        3dcalc -a $src -b rm.mean_r$run+tlrc -c $mask              \
               -expr 'c * min(200, a/b*100)*step(a)*step(b)'       \
               -prefix rm.pb06.$subj.r$run.scale

        # rename last, so a .HEAD under the final name means the run finished
        3drename rm.pb06.$subj.r$run.scale+tlrc pb06.$subj.r$run.scale
        rm -f rm.*
    end

    # --------------------------------------- merge: 3dTproject per motion limit
    foreach mot ( $todo )
        set mtag = m`echo $mot | sed 's/\./p/g'`
        set cdir = $postdir/$mtag
        set vdir = $sesdir/${baseId}${tagSep}${btag}${mtag}.${seqType}
        mkdir -p $vdir
        cd $vdir
        rm -f rm.errts.*

        # -- use 3dTproject to project out regression matrix --
        3dTproject -polort 0 -input $bdir/pb06.$subj.r*.scale+tlrc.HEAD  \
                   -mask $mask                                            \
                   -censor $cdir/censor_${subj}_combined_2.1D -cenmode ZERO \
                   -ort $cdir/X.nocensor.xmat.1D -prefix rm.errts.${subj}.tproject

        # record what produced this errts
        cp $cdir/censor_${subj}_combined_2.1D $cdir/motion_${subj}_censor.1D \
           $cdir/ROIPC.*.1D $cdir/X.xmat.1D $cdir/X.nocensor.xmat.1D .
        echo "base: $resdir"       >  out.post_params.txt
        echo "fwhm: $fwhm"         >> out.post_params.txt
        echo "motion limit: $mot"  >> out.post_params.txt
        echo "TRs kept: `1d_tool.py -infile censor_${subj}_combined_2.1D -show_trs_uncensored encoded`" \
                                   >> out.post_params.txt
        echo "created: `date`"     >> out.post_params.txt

        # rename last, so a .HEAD under the final name means it finished
        # (compression follows the server's AFNI_COMPRESSOR, as in the base run)
        3drename rm.errts.${subj}.tproject+tlrc errts.${subj}.tproject
    end

    if ( ! $keepPb06 ) rm -rf $bdir
end

echo "x07 finished: `date`"
