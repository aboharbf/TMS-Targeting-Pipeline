
import os
from utils import process_folder
from pathlib import Path
import pandas as pd

# Usage
resultDir = Path('~/pipeline/results').expanduser()
print(f'Processing {resultDir}')
df = process_folder(resultDir)

# Optional: Convert subject and session to integers if they are numeric
#df['subject'] = pd.to_numeric(df['subject'], errors='coerce')
#df['session'] = pd.to_numeric(df['session'], errors='coerce')

# Save to CSV
df.to_csv('coordinatesAll.csv', index=False)

print(f"\nProcessed {len(df)} files")
print(f"Columns: {list(df.columns)}")
print(df.head())
