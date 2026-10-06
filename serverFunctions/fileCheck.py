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
import analysisConfig as cfg
from utils import run_and_log, print_and_log, slurmScriptLogger, spaceTagFromTemplate, errtsPrefix, snapshotConfig

# Shared and analysis settings come from analysisConfig.py.
snapshotConfig(cfg)

# dir paths
dataDir = cfg.dataDir
outputDir = cfg.outputDir               # preprocScript.py's output root.

# Gather the full range of subjects present in the data directory.
subjVec = [item for item in os.listdir(dataDir) if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# Initial analysis, focus on subjects 100 and less.
subjVec = [s for s in subjVec if int(s) <= 100]

# As a test, just do the first 4
subjVec = subjVec[0:10]

sesVec = cfg.sesVec

print(f"Preparing scripts/runs on following subjects: {subjVec}")
print(f"Total Subject count: {len(subjVec)}")

seqVec = cfg.seqTypeVec
task = cfg.task

# Which preprocessing outputs to check.
runTag = cfg.runTag
spaceTag = spaceTagFromTemplate(cfg.tlrcBase)

output_file = 'fileCheck_results.txt'

with open(output_file, 'w') as f:
    # for each subject
        for seqType in seqVec:

            f.write(f"\n Checking for {seqType} \n\n")

            for subj in subjVec:
                for ses in sesVec:
                    # Files of interest: errts dataset prefix (.HEAD/.BRIK[.gz]).
                    errtsFile = errtsPrefix(outputDir, subj, ses, task, seqType, spaceTag, runTag)

                    if not os.path.exists(f"{errtsFile}.HEAD"):
                        f.write(f"{errtsFile} does not exist\n")

print(f"Results saved to {output_file}")                

            
