"""
Find sessions whose runs differ in length, and list what was made from them
with the wrong run split and has to be deleted and redone.

x07.blur_censor_param.csh used to split the motion files with 1d_tool.py
-set_nruns, which assumes equal-length runs. A session with an odd TR total
failed outright (subjects 60 and 69: 'invalid nruns = 2 (does not divide
nt = 577)'). One with an even total (e.g. 290 + 288) was split 289 + 289
without any error, so its grid variants put the run boundary in the wrong
place: motion demeaning, derivatives and censoring around it are off.
x07 now uses -set_run_lengths, and records the run lengths it used:
    post/m{M}/run_lengths.txt                    each censor branch
    {variant dir}/out.post_params.txt            'run lengths: 290 288'
so outputs made after the fix are told apart from ones made before it, and
running this again after a rerun doesn't flag the new outputs.

Per session, from the base run's run lengths (utils.runLengths):
    equal      nothing to do; skipped
    unequal    old-split outputs are listed for deletion:
                 variant dirs   no 'run lengths' record matching the base run,
                                or no errts (unfinished)
                 censor dirs    post/m* without a matching run_lengths.txt
                                (x07 rebuilds these itself now; listed in case
                                an older x07 is still deployed)
                 corr outputs   of a variant that's being deleted or gone, or
                                older than its variant (made from an earlier one)
               then rerun paramScript.py, corrScript.py, mergeOutputs.py.
               The base run and its corr outputs are fine (afni_proc handles
               unequal runs itself).
    unknown    base results dir there, but no pb04 or out.ss_review to read
               the run lengths from
Sessions with no base results dir are skipped.

Deletes nothing: the rm commands go in cleanupFile, to review and then run
(with no paramScript .post or corrScript .corr job of those subjects queued):
    bash runLengthCleanup.sh
Running this again afterwards should list nothing to delete.
"""

import os
import re
import glob

import analysisConfig as cfg
from utils import snapshotConfig, spaceTagFromTemplate, preprocNames, preprocPaths, runLengths, variantTag

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
gridTags = [variantTag(fwhm, mot) for fwhm in cfg.fwhmVec for mot in cfg.motVec]   # paramScript.py's grid

cleanupFile = 'runLengthCleanup.sh'     # In the current directory; overwritten each run.

# Any grid variant's run tag (utils.variantRunTag), whatever its fwhm/motion
# values, so variants from an older grid are found too. Group 'var' is the
# variant part (utils.variantTag).
varTagRe = (re.escape(runTag) + '-' if runTag else '') + r'(?P<var>b\d+(?:p\d+)?m\d+(?:p\d+)?)'

subjVec = [item for item in os.listdir(dataDir) if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

print(f"Checking subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}\n")


def readFirst(path, pattern):
    """Group 1 of the first line of path matching pattern, stripped; None if no file or no match."""
    try:
        with open(path) as fh:
            for line in fh:
                match = re.match(pattern, line)
                if match:
                    return match.group(1).strip()
    except OSError:
        pass
    return None


nEqual = 0
nNoBase = 0
unequal = []        # dicts, one per unequal session
unknown = []        # labels

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
            want = ' '.join(str(n) for n in lengths)        # as x07 writes $tr_counts

            # Variant results dirs next to the base one: preprocNames' scriptId with a variant run tag.
            # Good = finished, and out.post_params.txt records these run lengths.
            prefix = preprocNames(subj, ses, task, seqType, spaceTag)['baseId']
            dirRe = re.compile(rf"{re.escape(prefix)}_(?P<tag>{varTagRe})\.{re.escape(seqType)}")
            staleDirs = []
            goodTags = {}       # run tag -> time its out.post_params.txt was written
            goodVar = set()     # their variant parts, to compare with the grid
            for d in sorted(os.listdir(paths['outputSesDir'])):
                match = dirRe.fullmatch(d)
                vdir = f"{paths['outputSesDir']}/{d}"
                if not match or not os.path.isdir(vdir):
                    continue
                tag = match.group('tag')
                params = f"{vdir}/out.post_params.txt"
                finished = os.path.exists(f"{preprocPaths(outputDir, subj, ses, task, seqType, spaceTag, tag)['errts']}.HEAD")
                if finished and readFirst(params, r'run lengths:(.*)') == want:
                    goodTags[tag] = os.path.getmtime(params)
                    goodVar.add(match.group('var'))
                else:
                    staleDirs.append(vdir)

            # Censor branches without a matching run_lengths.txt.
            postDir = f"{paths['meDir']}/post"
            staleCensor = sorted(c for c in glob.glob(f"{postDir}/m*") if os.path.isdir(c)
                                 and readFirst(f"{c}/run_lengths.txt", r'(.*)') != want)

            # corrScript.py outputs of the variant run tags (named by utils.corrPaths), stale
            # unless their variant is good and they were made after it.
            subjResDir = f"{resultsDir}/{subj}"
            corrRe = re.compile(rf"{re.escape(f'{subj}.{ses}.{task}.{seqType}')}\.(?P<tag>{varTagRe})\.errts\.targ\..+")
            staleCorr = []
            if os.path.isdir(subjResDir):
                for f in sorted(os.listdir(subjResDir)):
                    match = corrRe.fullmatch(f)
                    if not match:
                        continue
                    tag = match.group('tag')
                    if tag not in goodTags or os.path.getmtime(f"{subjResDir}/{f}") < goodTags[tag]:
                        staleCorr.append(f"{subjResDir}/{f}")

            unequal.append({
                'label': label, 'lengths': lengths, 'source': source,
                'staleDirs': staleDirs, 'staleCensor': staleCensor, 'staleCorr': staleCorr,
                'nGood': len(goodTags), 'gridMissing': [t for t in gridTags if t not in goodVar],
                'sesDir': paths['outputSesDir'], 'postDir': postDir, 'subjResDir': subjResDir,
                'subj': subj,
            })

# --------------------------------------------------------------------- report
rerunSubj = []
for s in unequal:
    stale = s['staleDirs'] or s['staleCensor'] or s['staleCorr']
    print(f"{s['label']}: unequal runs, {' + '.join(str(n) for n in s['lengths'])} = {sum(s['lengths'])} TRs "
          f"(from {s['source']}); {s['nGood']} variant(s) already made with these run lengths")
    if stale:
        print("  delete (made with the old run split):")
        if s['staleDirs']:
            print(f"    {len(s['staleDirs'])} variant dir(s) in {s['sesDir']}:")
            print(f"      {' '.join(os.path.basename(d) for d in s['staleDirs'])}")
        if s['staleCensor']:
            print(f"    {len(s['staleCensor'])} censor dir(s) in {s['postDir']}: "
                  f"{' '.join(os.path.basename(c) for c in s['staleCensor'])}")
        if s['staleCorr']:
            print(f"    {len(s['staleCorr'])} corr output(s) in {s['subjResDir']}")
    if stale or s['gridMissing']:
        print("  then rerun: paramScript.py, corrScript.py, mergeOutputs.py" if stale else
              f"  {len(s['gridMissing'])} grid variant(s) still to make: rerun paramScript.py, corrScript.py, mergeOutputs.py")
        if s['subj'] not in rerunSubj:
            rerunSubj.append(s['subj'])
    else:
        print("  nothing to delete, every grid variant made; pipelineCheck.py's corr report shows their peak search")

for label in unknown:
    print(f"{label}: run lengths unknown (no pb04 or out.ss_review in the base results dir)")

nDelete = sum(1 for s in unequal if s['staleDirs'] or s['staleCensor'] or s['staleCorr'])
nChecked = nEqual + len(unequal) + len(unknown)
print(f"\nSummary: {nChecked} session(s) with a base run checked")
print(f"  {nEqual} equal run lengths: nothing to do")
print(f"  {len(unequal)} unequal run lengths: {nDelete} with old-split outputs to delete, "
      f"{len(unequal) - nDelete} without")
print(f"  {len(unknown)} unknown")
print(f"  ({nNoBase} subject/session/seqType(s) with no base run skipped)")
if rerunSubj:
    print(f"Subjects to rerun: {' '.join(rerunSubj)}")

# ------------------------------------------------------------- cleanup script
with open(cleanupFile, 'w') as f:
    f.write("#!/bin/bash\n")
    f.write("# Written by runLengthCheck.py: outputs of sessions with unequal run lengths\n")
    f.write("# made with the old run split (before x07 used -set_run_lengths). Review,\n")
    f.write("# check no paramScript (.post) or corrScript (.corr) job of these subjects\n")
    f.write("# is queued (squeue --me), then run: bash runLengthCleanup.sh\n")
    f.write("# Afterwards rerun paramScript.py, corrScript.py, mergeOutputs.py.\n")
    f.write("set -e\n\n")
    for s in unequal:
        if not (s['staleDirs'] or s['staleCensor'] or s['staleCorr']):
            continue
        f.write(f"# {s['label']}: {' + '.join(str(n) for n in s['lengths'])} TRs\n")
        for d in s['staleDirs'] + s['staleCensor']:
            f.write(f"rm -rf '{d}'\n")
        for c in s['staleCorr']:
            f.write(f"rm -f '{c}'\n")
        f.write("\n")
    if not nDelete:
        f.write("# nothing to delete\n")

print(f"Cleanup commands written to {cleanupFile} (review, then: bash {cleanupFile})")
