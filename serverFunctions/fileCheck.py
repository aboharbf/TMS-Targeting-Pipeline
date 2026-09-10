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

# Initial analysis, focus on subjects 100 and less.
subjVec = [s for s in subjVec if int(s) <= 100]

# As a test, just do the first 4
# subjVec = subjVec[0:3]

# Assume all subjects have 4 sessions
sesVec = ['01', '02', '03', '04']

print(f"Preparing scripts/runs on following subjects: {subjVec}")
print(f"Total Subject count: {len(subjVec)}")

# Parameter space to explore.
seqVec = ['se', 'me', 'se_e2'] # 'me'
task = 'rest'

output_file = 'fileCheck_results.txt'

with open(output_file, 'w') as f:
    # for each subject
        for seqType in seqVec:

            f.write(f"\n Checking for {seqType} \n\n")

            for subj in subjVec:
                for ses in sesVec:
                    # Files of interest
                    errtsFile = f"{dataDir}/{subj}/ses-{ses}/{subj}.results.task-{task}-mni.{seqType}/errts.{subj}.tproject+tlrc.BRIK" #.BRIK contains data, .HEAD is metadata.
                    errtsFile2 = f"{dataDir}/{subj}/ses-{ses}/{subj}.results.task-{task}-mni.{seqType}/errts.{subj}.tproject+tlrc.BRIK.gz" #.BRIK contains data, .HEAD is metadata.

                    if not os.path.exists(errtsFile) and not seqType == 'se_e2':
                        f.write(f"{errtsFile} does not exist\n")
                    elif not os.path.exists(errtsFile2) and seqType == 'se_e2':
                        f.write(f"{errtsFile2} dose not exist \n")

print(f"Results saved to {output_file}")                

            
