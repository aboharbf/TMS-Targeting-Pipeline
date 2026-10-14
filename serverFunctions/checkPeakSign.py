"""
Check the sign of the sgACC correlation at each peak in coordinatesAll.csv.

peakScript.py's 3dcalc step takes abs() of the Fisher z map before 3dclust, so
a reported peak can be a positive OR negative correlation. This reads the
UNMASKED map (3dTcorr1D's output, before abs) at each peak's coordinate and
records its sign. See futureChecks.md.

Map paths follow peakScript.py as first committed (f22b27a):
    {resultsDir}/{subj}/{subj}.{ses}.{task}.{seqType}.errts.targ.{tMask}.fisher.nii
with '.{runTag}' after seqType when the CSV has a runTag column (later outputs).
3dclust ran with -orient RAI, so the coordinates are read back with 3dmaskdump -dbox (RAI/DICOM).

Run on the cluster (needs AFNI):
    python checkPeakSign.py coordinatesAll.csv [resultsDir]
Writes <csv>_sign.csv next to the input, with corrZ and sign columns added.
"""

import sys
import subprocess
from pathlib import Path

import pandas as pd

csvPath = Path(sys.argv[1])
resultsDir = sys.argv[2] if len(sys.argv) > 2 else str(Path("~/pipeline/results").expanduser())   # peakScript's outDirMain

df = pd.read_csv(csvPath, dtype=str)    # str, so '001' / '02' keep their zeros


def corrMapPath(row):
    tag = row.get('runTag')
    dataId = f"{row['subject']}.{row['session']}.{row['task']}.{row['sequence_type']}"
    if isinstance(tag, str) and tag:
        dataId += f".{tag}"
    return f"{resultsDir}/{row['subject']}/{dataId}.errts.targ.{row['target']}.fisher.nii"


cache = {}      # (map, x, y, z) -> z value; the 3 dlPFC masks often share a peak


def valueAt(mapPath, x, y, z):
    key = (mapPath, x, y, z)
    if key not in cache:
        res = subprocess.run(["3dmaskdump", "-noijk", "-dbox", x, y, z, mapPath],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out = res.stdout.split()
        cache[key] = float(out[-1]) if res.returncode == 0 and out else None
    return cache[key]


corrZ, sign = [], []
for i, row in df.iterrows():
    mapPath = corrMapPath(row)
    if pd.isna(row['X']) or pd.isna(row['Y']) or pd.isna(row['Z']):
        val, s = None, 'no coordinates'
    elif not Path(mapPath).exists():
        val, s = None, 'map missing'
    else:
        val = valueAt(mapPath, row['X'], row['Y'], row['Z'])
        s = 'read failed' if val is None else ('negative' if val < 0 else 'positive' if val > 0 else 'zero')
    corrZ.append(val)
    sign.append(s)
    if (i + 1) % 500 == 0:
        print(f"{i + 1}/{len(df)} rows")

df['corrZ'] = corrZ
df['sign'] = sign

outPath = csvPath.with_name(csvPath.stem + '_sign.csv')
df.to_csv(outPath, index=False)

print(f"\n{df['sign'].value_counts().to_string()}\n")
print(pd.crosstab([df['sequence_type'], df['target']], [df['clustMask'], df['sign']]).to_string())
print(f"\nSaved {outPath}")
