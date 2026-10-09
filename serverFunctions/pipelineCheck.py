"""
Report, per subject and session, which files each pipeline stage needs or made.
One report per stage, each a .txt in the current directory, overwritten each run.

Stages so far:
    raw   inputs preprocScript.py needs (T1, echoes, sidecars), by the same
          rules: utils.rawT1 / rawSession.

============================== HOW TO ADD A STAGE ==============================
(e.g. 'preproc': does each session have its base-run errts?)

1. Rules in utils.py, not here. Put the code that finds and checks the stage's
   files in a utils function, and have the script that makes or reads those
   files call it too (as preprocScript.py calls rawSession). Then this report
   and the pipeline can't disagree about what counts as present.
   Have it return checks as (item, status, detail), status one of
   'found' / 'missing' / 'bad' / 'note', so describe() can turn them into a line.

2. A check function in this file, next to checkRaw():
       def checkPreproc(subj):
           lines = []        # report lines, one per session usually
           problems = []     # 'ses-XX: missing ...'; empty = subject complete
           for ses in sesVec:
               ...           # call the utils function
               lines.append(f"ses-{ses}: {describe(checks)}")
               problems += [f"ses-{ses}: {p}" for p in ...]
           return lines, problems

3. Its report file, next to outputFileRaw:
       outputFilePreproc = 'fileCheck_preproc.txt'

4. One writeReport() call at the bottom, with a title and the settings the
   stage was checked against (they're written into the report's header):
       writeReport(outputFilePreproc, "Base preprocessing outputs",
                   [("Output", outputDir), ("Run tag", runTag)], checkPreproc)

writeReport() handles everything else: the header, the 'Checking subject N...'
sections and the summary.
================================================================================
"""

import os
from datetime import datetime

import analysisConfig as cfg
from utils import snapshotConfig, rawT1, rawSession

# Shared and analysis settings come from analysisConfig.py.
snapshotConfig(cfg)

# dir paths
dataDir = cfg.dataDir                   # Inputs (T1, EPIs, sidecars); read only.

task = cfg.task
sesVec = cfg.sesVec
nEchoes = cfg.nEchoes

# Report files, in the current directory; overwritten each run.
outputFileRaw = 'fileCheck_raw.txt'

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
    """One report line from rawSession-style (item, status, detail) checks: 'found ...; missing ...; bad ...; note ...'."""
    parts = []
    for status in ('found', 'missing', 'bad', 'note'):
        items = [f"{i} ({d})" if d else i for i, s, d in checks if s == status]
        if items:
            parts.append(f"{status} " + ", ".join(items))
    return "; ".join(parts)


def writeReport(outputFile, title, settings, checkSubject):
    """
    Run checkSubject on every subject and write the report: a header (title and
    the settings it was checked against), a section per subject, then a summary
    of complete subjects and every problem found.
    """
    nComplete = 0
    allProblems = []

    with open(outputFile, 'w') as f:
        f.write(f"{title}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        for name, value in settings:
            f.write(f"{name}: {value}\n")
        f.write("\n")

        for subj in subjVec:
            lines, problems = checkSubject(subj)
            f.write(f"Checking subject {subj}...\n")
            for line in lines:
                f.write(f"  {line}\n")
            f.write("\n")

            if not problems:
                nComplete += 1
            allProblems += [f"{subj} {p}" for p in problems]

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
    else:
        extra = f"; {len(t1Vec) - 1} more match(es), preprocScript uses this one" if len(t1Vec) > 1 else ""
        lines.append(f"anat:   found T1 ({os.path.basename(t1Vec[0])}{extra})")

    for ses in sesVec:
        raw = rawSession(dataDir, subj, ses, task, nEchoes)
        lines.append(f"ses-{ses}: {describe(raw['checks'])}")
        problems += [f"ses-{ses}: {p}" for p in raw['problems']]

    return lines, problems


writeReport(outputFileRaw, "Raw inputs for preprocScript.py", [
    ("Data", dataDir),
    ("Task", task),
    ("Sessions", ' '.join(sesVec)),
    ("Echoes required", nEchoes),
], checkRaw)
