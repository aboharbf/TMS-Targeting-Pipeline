# Things to check

Open questions about what the pipeline computes, as opposed to new features
(`Future_ideas.md`) or design decisions (`pendingQuestions.md`).

## 2026-10-14 — Peak search (peakScript.py / corrScript.py)

- **Sign of the correlation (peakScript.py results).** Step 3 masks with
  `abs(a*ispositive(b-.5))`, which folds positive and negative Fisher z
  together, so a peak can be the dlPFC region most *positively* correlated with
  sgACC rather than the anticorrelated one TMS targeting usually wants.
  `serverFunctions/checkPeakSign.py` reads the unmasked map at each peak in a
  coordinatesAll.csv to show which. corrScript.py now also searches the
  negative and positive maps separately (`peakSignExpr` in analysisConfig.py;
  `.neg.` / `.pos.` in the names) and saves each peak's z. Compare its `abs`
  peaks with `neg` to see how often the original search picked a positive peak.
- **Which coordinate 3dclust reports.** The first cluster listed (3dclust sorts
  by size), and its max-intensity location (MI RL/AP/IS). With `-1clip .01`
  almost every in-mask voxel survives, so the "largest cluster" is probably
  most of the mask, and the result is close to the single peak voxel. Check
  that's intended, and compare with a stricter clip or 3dClusterize.
- **'none' outputs.** corrScript.py writes `none` when 3dclust runs but lists
  no cluster (e.g. no positive z anywhere in the mask); these come through
  mergeOutputs.py with empty X/Y/Z. Check how often, and whether they cluster in
  particular variants (heavy censoring, no blur).
- **Old empty outputs.** Before corrScript.py, peakScript.py's `tee` wrote a
  .1d even when 3dclust failed, and `[ -f ]` then skipped it forever.
  `utils.corrSession` reports these (and any 3-field .1d without the peak z) as
  `bad`, and corrScript.py redoes them. Check whether an existing
  `coordinatesAll.csv` has rows with empty X/Y/Z from such files.
- **SLURM resources are estimates.** `corrCpus = 1`, `corrMem = '8G'`,
  `corrTime = '08:00:00'` in analysisConfig.py. After subject 001, run
  `sacct -j <id> --format=MaxRSS,Elapsed` and tighten them.
- **Speed-up not taken yet.** 3dTcorr1D is still written inside the dlPFC mask
  loop (harmless, since `[ -f ]` skips the repeats, but a failure retries 3x).
  Reading the errts once per run tag, by `1dcat`-ing the seed and network traces
  into one 3dTcorr1D, would roughly halve run time.
