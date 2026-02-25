# This is a Python script which will mainly function to allow for the efficient generation of bash commands
# To-Do List
# - introduce intermediate commands which can generate .pngs to visualize results - Andy's Brain book fMRI tutorial seems to have good visualization info
# - Create function which can store 1d outputs as a csv cell, appropriately tagged with metadata/switches/variables from the loop executed to allow for proper averaging.
# - Create distinct script which looks into csv files, generates avg/std across different parameter sets for each subject.

# next task
# - Test run up until end, examine fxn with the pipes not included, figure out ideal method for data extraction.
# - Test run on 001, do additional test run with masked corr rather than whole brain, do additional one with 3dClusterize.
# - consider ideal output for .1d

import os
import subprocess
from utils import run_and_log, slurmScriptLogger
from pathlib import Path

# dir paths
projDir = Path("~").expanduser()
dataDir = f'{projDir}/nbthetaconn/data'
maskDir = f'{projDir}/nbthetaconn/masks'
outDirMain = f'{projDir}/pipeline/results'
slurmScriptDir = f'{projDir}/pipeline/slurm'
# consider output dir for final calculations

# Gather the full range of subjects present in the data directory.
subjVec = [item for item in os.listdir(dataDir) if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# As a test, just do the first 4
# subjVec = subjVec[0:3]

# Assume all subjects have 4 sessions
sesVec = ['01', '02', '03', '04']

print(f"Preparing scripts/runs on following subjects: {subjVec}")

# Parameter space to explore.
seqVec = ['se', 'me'] # 'me'

# Generate full path for the target mask. Double brackets act as a placeholder for template formating function.
maskTemplate = f"{maskDir}/subgenual_{{}}_mask.nii"
maskTypeVec = ['seed', 'network'] # 'network', Anatomical vs network based sgACC activity identification.
maskPathVec = [maskTemplate.format(maskT) for maskT in maskTypeVec] 

# Generate full path for the cluster search mask
clustMaskTemplate = f"{maskDir}/Parcels_MNI_222.resam.ldlpfc.neurosynth.{{}}.nii"
clustMaskVec = ['orig', 'dilate_5', 'erode_1']
clustMaskPathVec = [clustMaskTemplate.format(cMask) for cMask in clustMaskVec]

task = 'rest'

scriptMode = 0 # the overall script behavior. 0 = slurm, 1 = run in python, 2 = both.

# for each subject
for subj in subjVec:

    # Output Path
    outDir = f"{outDirMain}/{subj}"
    os.makedirs(outDir, exist_ok=True)

    for ses in sesVec:
        for seqType in seqVec:
            # Files of interest
            errtsFile = f"{dataDir}/{subj}/ses-{ses}/{subj}.results.task-{task}-mni.{seqType}/errts.{subj}.tproject+tlrc.BRIK" #.BRIK contains data, .HEAD is metadata.
            dataIDstr = f"{subj}.{ses}.{task}.{seqType}"
            run_and_log(f"echo ### Starting Subject {subj}, session {ses} ###, sequence type {seqType}")
            
            logger = slurmScriptLogger(subj, ses, task, seqType, slurmScriptDir)

            for tMask, maskPath in zip(maskTypeVec, maskPathVec):
                # for the mask of interest, generate the trace to be correlated against now.
                run_and_log(f"echo ### ### Generating mask of target activity using sgACC {tMask} mask")
                        
                avgPath = f"{outDir}/{dataIDstr}.errts.targ.{tMask}.1d"

                # Step 1 - average across the sgACC mask, creating a single time series.
                # This time series will be the object of correlation

                bsCmd = rf"3dmaskave -quiet -mask {maskPath} {errtsFile} > {avgPath}"
                
                # Add a check to see if the avgPath file already exists. If so, skip.
                if os.path.exists(avgPath):
                    run_and_log(rf"echo {avgPath} already exists. Will not rerun 3dmaskave")
                elif scriptMode > 0:
                    run_and_log(bsCmd)

                if scriptMode != 1:
                    slurmCmd = f"""[ -f {avgPath} ] || {bsCmd}"""
                    logger.append(slurmCmd)

                for cMask, cMaskPath in zip(clustMaskVec, clustMaskPathVec):

                    run_and_log(f"### ### ### performing cluster search in dlPFC {cMask} mask")

                    # The path below defines the mask to be used prior to a cluster search - for now, left dlPFC.
                    # clustMaskPath = f"{maskDir}/Parcels_MNI_222.resam.ldlpfc.neurosynth.{cMask}.nii"

                    # Output paths
                    #corrPath = f"{outDir}/{dataIDstr}.errts.targ.{mask}.fischer.clust.ldlpfc.{cMask}.nii" # Future name when corr include -mask

                    # For now, 2 distinct output paths - corrPath for brain wide, corrMaskPath for masked to target.
                    corrPath = f"{outDir}/{dataIDstr}.errts.targ.{tMask}.fisher.nii" # Output file for brain wide correlations to target trace.
                    corrMaskPath = f"{outDir}/{dataIDstr}.errts.targ.{tMask}.fisher.clust.ldlpfc.{cMask}.nii"
                    # Once the masked correlation map is generated, identify clusters within.
                    corrClustOutPath = f"{outDir}/{dataIDstr}.errts.targ.{tMask}.fisher.clust.ldlpfc.{cMask}.1d" # Coordinates for the desired cluster outputs.

                    # Step 2 - correlate with the whole brain
                    # - prefix appears to be a way to denote the entire output file name.
                    # could be improved upon using the -mask fxn with the dlPFC mask here.

                    bsCmd2 = rf"3dTcorr1D -Fisher -prefix {corrPath} {errtsFile} {avgPath}"
                    if os.path.exists(corrPath):
                        run_and_log(rf"echo {corrPath} already exists. Will not run 3dTcorr1D")
                    elif scriptMode > 0:
                        run_and_log(bsCmd2)

                    if scriptMode != 1:
                        slurmCmd2 = f"""[ -f {corrPath} ] || {bsCmd2}"""
                        logger.append(slurmCmd2)
                    
                    # Varies depending on the size/nature of the dlPFC mask
                    # mask will dilate/erode, consider additional loops here to consider this.

                    # Step 3 - mask by the dlPFC.
                    bsCmd3 = rf"""3dcalc -a {corrPath} -b {cMaskPath} -expr "abs(a*ispositive(b-.5))" -prefix {corrMaskPath}"""
                    if os.path.exists(corrMaskPath):
                        run_and_log(rf"echo {corrMaskPath} already exists. Will not run 3dcalc masking procedure")
                    elif scriptMode > 0:
                        run_and_log(bsCmd3)

                    if scriptMode != 1:
                        slurmCmd3 = f"""[ -f {corrMaskPath} ] || {bsCmd3}"""
                        logger.append(slurmCmd3)


                    # Step 4 - Identify the appropriate clusters
                    # The best spot won't likely come from a simple 'max' function.
                    # consider smoothing/softmax.
                    # per AFNI docs, might want to update to 3dClusterize.
                    # tee at the end is the final output, 1d file.
                    # The series of |'s at the end is for saving outputs to various objects.

                    bsCmd4 = rf"""3dclust -quiet -orient RAI -1clip .01 3.5 2 {corrMaskPath} \
                           | head -n1 \
                           | tr -s ' ' \
                           | cut -d" " -f15-17 \
                           | tee {corrClustOutPath}""" 

                    if os.path.exists(corrClustOutPath):
                        run_and_log(rf"echo {corrClustOutPath} already exists. Will not run 3dclust")
                    elif scriptMode > 0:
                        run_and_log(bsCmd4)

                    if scriptMode != 1:
                        slurmCmd4 = f"""[ -f {corrClustOutPath} ] || {bsCmd4}"""
                        logger.append(slurmCmd4)
                    
                    compStr = f"echo ######### Completed processing Subj-{subj} ses-{ses} seq-{seqType} with sgACC {tMask}, dlPFC {cMask} ########"
                    run_and_log(compStr)
                    logger.append(compStr)

