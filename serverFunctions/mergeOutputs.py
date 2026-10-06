
import os
from utils import process_folder, decodeRunTag
from pathlib import Path
import pandas as pd

import analysisConfig as cfg

# Usage
resultDir = Path('~/pipeline/results').expanduser()
print(f'Processing {resultDir}')
df = process_folder(resultDir)

# fwhm and motion per row, decoded from the run tag; the base run's come from its settings.
if not df.empty:
    decoded = [decodeRunTag(tag, cfg.runTag, cfg.preprocBlur, cfg.preprocCensorMotion) for tag in df['runTag']]
    df['fwhm'] = [fwhm for fwhm, _ in decoded]
    df['motion'] = [mot for _, mot in decoded]

# Optional: Convert subject and session to integers if they are numeric
#df['subject'] = pd.to_numeric(df['subject'], errors='coerce')
#df['session'] = pd.to_numeric(df['session'], errors='coerce')

# Save to CSV
df.to_csv('coordinatesAll.csv', index=False)

print(f"\nProcessed {len(df)} files")
print(f"Columns: {list(df.columns)}")
print(df.head())
