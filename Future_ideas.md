# Future ideas

## 2026-10-01 11:36 — Per-variant QC in f07

`preproc/f07.rest_post_temp.csh` stops at the 3dTproject errts, so each
blur x motion variant has no TSNR / ROI stats. TSNR depends on both blur and
censoring, so it would go in the merge loop:

- build `ktrs` from the variant's `censor_${subj}_combined_2.1D`
  (`1d_tool.py -show_trs_uncensored space`, proc script lines 463-466)
- TSNR = mean(pb06 over kept TRs) / stdev(errts over kept TRs)
  (proc script lines 569-573)
- per-region stats via `compute_ROI_stats.tcsh`, reusing the base run's
  `ROI_import_MNI_resam+tlrc` (not blur/censor dependent)
- must run before `rm -rf $bdir` (pb06 is deleted unless `keepPb06 = 1`)
