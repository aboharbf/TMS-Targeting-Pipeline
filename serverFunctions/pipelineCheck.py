"""
Report, per subject and session, which files each pipeline stage needs or made.
One report per stage, each a .txt in the current directory, overwritten each run.

Stages so far:
    raw       inputs preprocScript.py needs (T1, echoes, sidecars), by the same
              rules: utils.rawT1 / rawSession.
    preproc   what preprocScript.py's job leaves in each session's results dir
              (out.ss_review, base errts, x07's inputs): utils.preprocSession.
              Covers the errts check fileCheck.py used to make.
    param     paramScript.py's grid: each fwhm x motion variant's errts, from
              x07.blur_censor_param.csh: utils.paramSession. A session missing
              variants also notes when its base run isn't ready (paramScript
              skips those).
    corr      corrScript.py's peak search over every run tag (base + grid
              variants): a clust .1d per sgACC mask x dlPFC mask x peak sign,
              by utils.corrSession / clustDone. Run tags with no errts yet are
              noted as waiting on preproc/param.

============================== HOW TO ADD A STAGE ==============================
(e.g. 'merge': does each subject have mergeOutputs.py's results?)

1. Rules in utils.py, not here. Put the code that finds and checks the stage's
   files in a utils function, and have the script that makes or reads those
   files call it too (as preprocScript.py calls rawSession). Then this report
   and the pipeline can't disagree about what counts as present.
   Have it return checks as (item, status, detail), status one of
   'found' / 'missing' / 'bad' / 'note', so addLine() / describe() can turn
   them into a line (and leave out what reportFound says to).

2. A check function in this file, next to checkCorr():
       def checkMerge(subj):
           lines = []        # report lines, one per session usually
           problems = []     # 'ses-XX: missing ...'; empty = subject complete
           for ses in sesVec:
               ...           # call the utils function
               addLine(lines, f"ses-{ses}", checks)
               problems += [f"ses-{ses}: {p}" for p in ...]
           return lines, problems

3. Its report file, next to outputFileCorr:
       outputFileMerge = 'fileCheck_merge.txt'

4. One writeReport() call at the bottom, with a title and the settings the
   stage was checked against (they're written into the report's header):
       writeReport(outputFileMerge, "Merged outputs",
                   [("Results", resultsDir), ("Run tag", runTag)], checkMerge)

writeReport() handles everything else: the header, the 'Checking subject N...'
sections and the summary.
================================================================================
"""

import os
from datetime import datetime

import analysisConfig as cfg
from utils import (snapshotConfig, spaceTagFromTemplate, variantRunTag, rawT1, rawSession, preprocSession,
                   paramSession, corrSession)

# True = report everything checked, found or not. False = only what's missing or
# bad (plus notes on those sessions, which say why); complete sessions and
# subjects are left out of the sections, but still counted in the summary.
reportFound = True

# Shared and analysis settings come from analysisConfig.py.
snapshotConfig(cfg)

# dir paths
dataDir = cfg.dataDir                   # Inputs (T1, EPIs, sidecars); read only.
outputDir = cfg.outputDir               # preprocScript.py's output root.
resultsDir = cfg.resultsDir             # corrScript.py's output root, one subdir per subject.

task = cfg.task
sesVec = cfg.sesVec
nEchoes = cfg.nEchoes
runTag = cfg.runTag                     # Base run tag.
seqType = 'me'                          # As preprocScript.py: its afni_proc command is multi-echo only.
spaceTag = spaceTagFromTemplate(cfg.tlrcBase)
fwhmVec = cfg.fwhmVec                   # paramScript.py's grid.
motVec = cfg.motVec

# corrScript.py's search: every run tag (base + grid variants) x sgACC mask x dlPFC mask x peak sign.
runTagVec = [runTag] + [variantRunTag(runTag, fwhm, mot) for fwhm in fwhmVec for mot in motVec]
maskTypeVec = cfg.maskTypeVec
clustMaskVec = cfg.clustMaskVec
signVec = list(cfg.peakSignExpr)

# Report files, in the current directory; overwritten each run.
outputFileRaw = 'fileCheck_raw.txt'
outputFilePreproc = 'fileCheck_preproc.txt'
outputFileParam = 'fileCheck_param.txt'
outputFileCorr = 'fileCheck_corr.txt'

# Gather the full range of subjects present in the data directory.
subjVec = [item for item in os.listdir(dataDir) if os.path.isdir(os.path.join(dataDir, item))]
subjVec.sort(key=lambda x: int(x))

# Initial analysis, focus on subjects 100 and less.
# subjVec = [s for s in subjVec if int(s) <= 100]

# As a test, just do the first few
# subjVec = subjVec[0:10]

print(f"Checking subjects: {subjVec}")
print(f"Total subject count: {len(subjVec)}")


def describe(checks):
    """
    One report line from rawSession-style (item, status, detail) checks: 'found ...; missing ...; bad ...; note ...'.
    With reportFound False, 'found' is left out, and the line is '' (not reported) when nothing is missing or bad.
    """
    if not reportFound and not any(s in ('missing', 'bad') for _, s, _ in checks):
        return ''
    parts = []
    for status in ('found', 'missing', 'bad', 'note') if reportFound else ('missing', 'bad', 'note'):
        items = [f"{i} ({d})" if d else i for i, s, d in checks if s == status]
        if items:
            parts.append(f"{status} " + ", ".join(items))
    return "; ".join(parts)


def addLine(lines, label, checks):
    """Append 'label: describe(checks)' to lines, unless describe has nothing to report."""
    text = describe(checks)
    if text:
        lines.append(f"{label}: {text}")


def writeReport(outputFile, title, settings, checkSubject):
    """
    Run checkSubject on every subject and write the report: a header (title and
    the settings it was checked against), a section per subject, then a summary
    of complete subjects and every problem found. With reportFound False, a
    subject with nothing to report gets no section.
    """
    nComplete = 0
    allProblems = []

    with open(outputFile, 'w') as f:
        f.write(f"{title}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Showing: {'everything checked' if reportFound else 'missing/bad only'}\n")
        for name, value in settings:
            f.write(f"{name}: {value}\n")
        f.write("\n")

        for subj in subjVec:
            lines, problems = checkSubject(subj)
            if not problems:
                nComplete += 1
            allProblems += [f"{subj} {p}" for p in problems]

            if not lines:
                continue
            f.write(f"Checking subject {subj}...\n")
            for line in lines:
                f.write(f"  {line}\n")
            f.write("\n")

        summary = f"Summary: {nComplete}/{len(subjVec)} subjects complete"
        f.write(summary + "\n")
        for p in allProblems:
            f.write(f"  {p}\n")

    print(summary)
    print(f"Results saved to {outputFile}")


# ----------------------------------------------------------------- raw inputs
def checkRaw(subj):
    lines = []
    problems = []

    t1Vec = rawT1(dataDir, subj)
    if not t1Vec:
        lines.append("anat:   missing T1")
        problems.append("anat: missing T1")
    elif reportFound:
        extra = f"; {len(t1Vec) - 1} more match(es), preprocScript uses this one" if len(t1Vec) > 1 else ""
        lines.append(f"anat:   found T1 ({os.path.basename(t1Vec[0])}{extra})")

    for ses in sesVec:
        raw = rawSession(dataDir, subj, ses, task, nEchoes)
        addLine(lines, f"ses-{ses}", raw['checks'])
        problems += [f"ses-{ses}: {p}" for p in raw['problems']]

    return lines, problems


# ------------------------------------------------------- base preproc outputs
def checkPreproc(subj):
    lines = []
    problems = []

    for ses in sesVec:
        pre = preprocSession(outputDir, subj, ses, task, seqType, spaceTag, runTag)
        addLine(lines, f"ses-{ses}", pre['checks'])
        problems += [f"ses-{ses}: {p}" for p in pre['problems']]

    return lines, problems


# ----------------------------------------------------- parameter grid outputs
def checkParam(subj):
    lines = []
    problems = []

    for ses in sesVec:
        par = paramSession(outputDir, subj, ses, task, seqType, spaceTag, runTag, fwhmVec, motVec)
        checks = par['checks']

        # Why variants are missing, when paramScript.py won't start them yet
        # (its own skip tests, in its order).
        if par['todo']:
            pre = preprocSession(outputDir, subj, ses, task, seqType, spaceTag, runTag)
            if not pre['done']:
                checks = checks + [('base run', 'note', f"not finished, so paramScript skips it; see {outputFilePreproc}")]
            elif pre['missingInputs']:
                checks = checks + [('base run', 'note', f"lacks x07 inputs, so paramScript skips it; see {outputFilePreproc}")]

        addLine(lines, f"ses-{ses}", checks)
        problems += [f"ses-{ses}: {p}" for p in par['problems']]

    return lines, problems


# --------------------------------------------------------- peak search outputs
def checkCorr(subj):
    lines = []
    problems = []

    for ses in sesVec:
        cor = corrSession(outputDir, resultsDir, subj, ses, task, seqType, spaceTag,
                          runTagVec, maskTypeVec, clustMaskVec, signVec)
        checks = cor['checks']

        # Run tags corrScript.py can't start yet: their errts come from preproc/param.
        if cor['notReady']:
            checks = checks + [('errts', 'note', f"made by preproc/param; see {outputFilePreproc}, {outputFileParam}")]

        addLine(lines, f"ses-{ses}", checks)
        problems += [f"ses-{ses}: {p}" for p in cor['problems']]

    return lines, problems


writeReport(outputFileRaw, "Raw inputs for preprocScript.py", [
    ("Data", dataDir),
    ("Task", task),
    ("Sessions", ' '.join(sesVec)),
    ("Echoes required", nEchoes),
], checkRaw)

writeReport(outputFilePreproc, "Base preprocessing outputs from preprocScript.py", [
    ("Output", outputDir),
    ("Task", task),
    ("Sessions", ' '.join(sesVec)),
    ("Run tag", runTag),
    ("Space", spaceTag),
    ("Seq type", seqType),
], checkPreproc)

writeReport(outputFileParam, "Parameter grid outputs from paramScript.py (x07.blur_censor_param.csh)", [
    ("Output", outputDir),
    ("Task", task),
    ("Sessions", ' '.join(sesVec)),
    ("Base run tag", runTag),
    ("Space", spaceTag),
    ("Seq type", seqType),
    ("Blur FWHM", ' '.join(fwhmVec)),
    ("Motion limits", ' '.join(motVec)),
    ("Variants per session", len(fwhmVec) * len(motVec)),
], checkParam)

writeReport(outputFileCorr, "sgACC -> dlPFC peak search outputs from corrScript.py", [
    ("Results", resultsDir),
    ("Output (errts)", outputDir),
    ("Task", task),
    ("Sessions", ' '.join(sesVec)),
    ("Space", spaceTag),
    ("Seq type", seqType),
    ("Run tags", f"{len(runTagVec)}: {' '.join(runTagVec)}"),
    ("sgACC masks", ' '.join(maskTypeVec)),
    ("dlPFC masks", ' '.join(clustMaskVec)),
    ("Peak signs", ' '.join(signVec)),
    ("Clust outputs per run tag", len(maskTypeVec) * len(clustMaskVec) * len(signVec)),
], checkCorr)
