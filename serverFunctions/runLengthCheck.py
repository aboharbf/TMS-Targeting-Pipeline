"""
Find sessions whose runs differ in length, and list what has to be redone for them.

x07.blur_censor_param.csh used to split the motion files with 1d_tool.py
-set_nruns, which assumes equal-length runs. A session with an odd TR total
failed outright (subjects 60 and 69: 'invalid nruns = 2 (does not divide
nt = 577)'). One with an even total (e.g. 290 + 288) was split 289 + 289
without any error, so its grid variants put the run boundary in the wrong
place: motion demeaning, derivatives and censoring around it are off. x07 now
uses -set_run_lengths, so redoing those sessions fixes them.

Per session, from the base run's run lengths (utils.runLengths):
    equal      nothing to do
    unequal    its grid variant dirs, post/ dir, and the corr outputs made from
               the variants are listed for deletion; then rerun paramScript.py,
               corrScript.py and mergeOutputs.py. The base run and its corr
               outputs are fine (afni_proc handles unequal runs itself).
    unknown    base results dir there, but no pb04 or out.ss_review to read
               the run lengths from
Sessions with no base results dir are skipped.

Deletes nothing: the rm commands go in cleanupFile, to review and then run
(with no paramScript .post or corrScript .corr job of those subjects queued):
    bash runLengthCleanup.sh
"""

import os
import re

import analysisConfig as cfg
from utils import snapshotConfig, spaceTagFromTemplate, preprocNames, preprocPaths, runLengths

# Shared and analysis settings come from analysisConfig.py.
snapshotConfig(cfg)

# dir paths
dataDir = cfg.dataDir                   # Inputs; only used for the subject list.
outputDir = cfg.outputDir               # preprocScript.py's / x07's output root.
resultsDir = cfg.resultsDir             # corrScript.py's output root, one subdir per subject.

task = cfg.task
sesVec = cfg.sesVec
seqTypeVec = cfg.seqTypeVec
runTag = cfg.runTag                     # Base run tag.
spaceTag = spaceTagFromTemplate(cfg.tlrcBase)

cleanupFile = 'runLengthCleanup.sh'     # In the current directory; overwritten each run.

# Any grid variant's run tag (utils.variantRunTag), whatever its fwhm/motion
# values, so variants from an older grid are found too.
varTagRe = (re.escape(runTag) + '-' if runTag else '') + r'b\d+(?:p\d+)?m\d+(?:p\d+)?'

subjVec = [item for item in os.listdir(dataDir) if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

print(f"Checking subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}\n")

nEqual = 0
nNoBase = 0
unequal = []        # (label, lengths, source, paths to delete)
unknown = []        # label
rerunSubj = []      # subjects with an unequal session, in order

for subj in subjVec:
    for seqType in seqTypeVec:
        for ses in sesVec:
            label = f"{subj} ses-{ses} {seqType}"
            paths = preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, runTag)
            if not os.path.isdir(paths['meDir']):
                nNoBase += 1
                continue

            lengths, source = runLengths(outputDir, subj, ses, task, seqType, spaceTag, runTag)
            if lengths is None:
                unknown.append(label)
                continue
            if len(set(lengths)) == 1:
                nEqual += 1
                continue

            # Variant results dirs next to the base one: preprocNames' scriptId with a variant run tag.
            prefix = preprocNames(subj, ses, task, seqType, spaceTag)['baseId']
            dirRe = re.compile(rf"{re.escape(prefix)}_{varTagRe}\.{re.escape(seqType)}")
            varDirs = sorted(f"{paths['outputSesDir']}/{d}" for d in os.listdir(paths['outputSesDir'])
                             if dirRe.fullmatch(d) and os.path.isdir(f"{paths['outputSesDir']}/{d}"))

            # x07's intermediates (motion files, censor and blur dirs), built with the old split.
            postDir = [f"{paths['meDir']}/post"] if os.path.isdir(f"{paths['meDir']}/post") else []

            # corrScript.py outputs of the variant run tags, named by utils.corrPaths.
            subjResDir = f"{resultsDir}/{subj}"
            corrRe = re.compile(rf"{re.escape(f'{subj}.{ses}.{task}.{seqType}')}\.{varTagRe}\.errts\.targ\..+")
            corrFiles = []
            if os.path.isdir(subjResDir):
                corrFiles = sorted(f"{subjResDir}/{f}" for f in os.listdir(subjResDir) if corrRe.fullmatch(f))

            unequal.append((label, lengths, source, varDirs, postDir, corrFiles))
            if subj not in rerunSubj:
                rerunSubj.append(subj)

# --------------------------------------------------------------------- report
for label, lengths, source, varDirs, postDir, corrFiles in unequal:
    runs = ' + '.join(str(n) for n in lengths)
    print(f"{label}: unequal runs, {runs} = {sum(lengths)} TRs (from {source})")
    if varDirs or corrFiles:
        print(f"  delete: {len(varDirs)} variant dir(s), {len(corrFiles)} corr output(s)"
              + (", post/" if postDir else ""))
        print("  then rerun: paramScript.py, corrScript.py, mergeOutputs.py")
    else:
        print("  no variants made yet" + (" (delete post/)" if postDir else ""))
        print("  rerun: paramScript.py, corrScript.py, mergeOutputs.py")

for label in unknown:
    print(f"{label}: run lengths unknown (no pb04 or out.ss_review in the base results dir)")

nChecked = nEqual + len(unequal) + len(unknown)
nDelete = sum(1 for _, _, _, v, p, c in unequal if v or p or c)
print(f"\nSummary: {nChecked} session(s) with a base run checked")
print(f"  {nEqual} equal run lengths: nothing to do")
print(f"  {len(unequal)} unequal run lengths, {nDelete} of them with outputs to delete")
print(f"  {len(unknown)} unknown")
print(f"  ({nNoBase} subject/session/seqType(s) with no base run skipped)")
if rerunSubj:
    print(f"Subjects to rerun: {' '.join(rerunSubj)}")

# ------------------------------------------------------------- cleanup script
with open(cleanupFile, 'w') as f:
    f.write("#!/bin/bash\n")
    f.write("# Written by runLengthCheck.py: grid variant outputs of sessions with unequal\n")
    f.write("# run lengths, made before x07 used -set_run_lengths. Review, check no\n")
    f.write("# paramScript (.post) or corrScript (.corr) job of these subjects is queued\n")
    f.write("# (squeue --me), then run: bash runLengthCleanup.sh\n")
    f.write("# Afterwards rerun paramScript.py, corrScript.py, mergeOutputs.py.\n")
    f.write("set -e\n\n")
    for label, lengths, source, varDirs, postDir, corrFiles in unequal:
        if not (varDirs or postDir or corrFiles):
            continue
        f.write(f"# {label}: {' + '.join(str(n) for n in lengths)} TRs\n")
        for d in varDirs + postDir:
            f.write(f"rm -rf '{d}'\n")
        for c in corrFiles:
            f.write(f"rm -f '{c}'\n")
        f.write("\n")
    if not nDelete:
        f.write("# nothing to delete\n")

print(f"Cleanup commands written to {cleanupFile} (review, then: bash {cleanupFile})")
