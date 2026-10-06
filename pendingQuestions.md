# Pending questions: peakScript over the blur x motion grid

Context: paramScript.py has run the 4x4 grid (fwhm 0/2/4/6 x motion 0/0.15/0.3/0.45)
on subject 1. peakScript.py currently reads only one run tag and names its outputs
without it, so it can't compare variants. Each item below can be decided and
implemented on its own.

Status key: OPEN / DECIDED / DONE

---

## 1. Shared analysis config — DONE

`serverFunctions/analysisConfig.py`, a plain Python file of settings (the
cluster's Python 3.6 rules out TOML; JSON has no comments). Read by
preprocScript, paramScript, peakScript and fileCheck. It holds:
- paths, and the shared naming settings (runTag, task, seqTypeVec, sesVec, tlrcBase)
- the base run's afni_proc values (blur, censor motion/outliers, firstTRs),
  directly above the grid (fwhmVec, motVec)
- peakScript's sgACC and dlPFC masks
- SLURM CPUs/memory/time, separately for preproc and param

Per-script switches (dryRun, submit, maxJobs, scriptMode, subjVec) stay in the
scripts. `variantTag` / `variantRunTag` moved to utils.py (code, not settings).

Each run calls `utils.snapshotConfig(cfg)`, which copies the imported file to
`~/pipeline/scripts/logs/session_<ts>.analysisConfig.py`, next to that run's
session log, and logs its path and sha256 there.

peakScript also saves the same timestamped copy into each subject's results
folder (`~/pipeline/results/{subj}/`). Existing outputs are skipped rather than
redone, so a copy records that a run used that folder, not that it produced
every file there; the run tag in output names (item 2) does that part.

## 2. Run tag in peakScript output names — DONE

Add the run tag as the 5th field of every output name:
`001.01.rest.me.param-b4m0p3.errts.targ.seed.fisher.clust.ldlpfc.orig.1d`

- Why it's needed: inputs come from separate per-variant preprocessing folders, but
  every variant writes into the same `results/{subj}/` folder under the same names.
  Because each step is skip-if-exists, the first run to finish (e.g. `param`)
  makes the others skip every step, so all variants silently report the first
  run's results. Fix: put the tag in the name (below) or use a per-variant subfolder.
- Fields 1-4 keep their meaning, so mergeOutputs needs only a small change.
- The base run's outputs carry its tag too (`001.01.rest.me.param.errts...`), so
  they can't be mistaken for the older untagged results in `~/pipeline/results/`,
  which may include f06-derived data (the old resolveErrts fallback). This doesn't
  touch the base run's preprocessing folder (see 6).
- Decision: tag in the name. Done in peakScript (`dataIDstr`); mergeOutputs'
  parser is unaffected (it reads fields 1-4 and finds 'targ'/'clust' by name).

## 3. SLURM job layout — DONE

One job script per subject/session running all 16 variants, instead of one per
variant (64 scripts for subject 1 alone).

- Each variant is light (2 3dmaskave, 2 3dTcorr1D, 6 3dcalc, 6 3dclust), and the
  existing skip-if-exists checks keep reruns safe per variant.
- Decision: one job script per subject/session, running all variants. Done:
  peakScript loops over `[runTag] + every variantRunTag`, skipping (and logging)
  run tags with no errts; the script is named without a tag (`slurm_job-001.01.rest.me.sh`).

## 4. mergeOutputs columns — DONE

Add `runTag`, `fwhm` and `motion` columns, decoded from the tag
(`b4m0p3` -> fwhm 4, motion 0.3). Old untagged files get an empty `runTag`.

- Depends on 2.
- Decision: add `runTag`, `fwhm`, `motion` as described. The base tag (`param`)
  has no encoded values, so its `fwhm`/`motion` are filled in from the base run's
  settings in analysisConfig.py (blur 4, censor motion 0.3).
- Done: utils.extract_filename_variables reads `runTag` (field 5, or empty when
  field 5 is `errts`); utils.decodeRunTag gives fwhm/motion; mergeOutputs adds them.

## 5. Subject scope — DECIDED

Limit peakScript to subject 1 (`subjVec[0:1]`) to match paramScript, instead of
the current `subjVec[0:10]`.

- Decision: keep `subjVec[0:10]`. Subjects without a variant's errts are already
  skipped (`SKIP: ... errts not found`), so only subject 1 gets the grid for now.

## 6. Base `param` run — DECIDED

Decision: include the base run in the comparison. Its preprocessing folder
(`..._mni_param.me`) keeps its name; nothing here renames it.

- The base run (preprocScript.py's afni_proc settings) used `-blur_size 4`,
  `-regress_censor_motion 0.3`, `-regress_censor_outliers 0.15`.
- So grid variant `param-b4m0p3` is the base run rebuilt by f07 with the same
  settings: the double-check. Its peaks should match the base run's. Any
  difference means f07's rebuild differs from afni_proc's regression, and is
  worth understanding before trusting the other 15 cells.
