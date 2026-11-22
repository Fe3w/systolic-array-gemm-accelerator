# Applying the README rework

## Important: apply it in the development repo, not the public one

Per D-034, the public repo is rebuilt from your private development repo by
the publishing script and is never edited by hand. If you edit the public repo
directly, the next publish overwrites your changes. So apply this in the dev
repo, then republish.

## Option A: patch (fastest)

```bash
cd /home/abhishek/MY-WORKFLOW/projects/SysArray      # your dev repo
git checkout -b readme-rework
git apply --check /path/to/sysarray-readme-rework.patch   # dry run
git apply /path/to/sysarray-readme-rework.patch
```

If the dev repo's README, `docs/waveforms/README.md` or `docs/LOCAL_SETUP.md`
differs from the public copy, `git apply` will refuse. Use `git apply --3way`,
or use option B.

## Option B: copy the files

The `repo/` folder in this kit mirrors repo paths. Copy these over:

| File | What changed |
| --- | --- |
| `README.md` | Rewritten: architecture, performance and compiler first; verification and PPA kept but shorter |
| `docs/PERFORMANCE.md` | New: full per-shape table, double-buffering analysis, roofline, tile order, SCALE-Sim (moved from README, plus a roofline explanation) |
| `docs/PPA.md` | New: FPGA and SKY130 sections, moved from the README unchanged, plus a summary and reproduce commands |
| `docs/VERIFICATION.md` | New: method, campaign coverage table (from `campaign_cd2849e.json`), what is not covered |
| `docs/waveforms/README.md` | Now holds the "See it run" content moved from the README |
| `docs/LOCAL_SETUP.md` | One line: pointer to "See it run" now points to `docs/waveforms/README.md` |
| `scripts/report/readme_figures.py` | New: generates `docs/img/flow.png` and `docs/img/utilization_before_after.png` from the perf CSVs |
| `scripts/report/test_readme_figures.py` | New: smoke test for the script |
| `docs/img/flow.png`, `docs/img/utilization_before_after.png` | New figures (regenerate with the script) |

## Then check

```bash
python3 scripts/report/readme_figures.py    # regenerate the two figures
make docs-check                             # links + cited results/ paths (passes: 22 files, 0 problems)
python3 -m pytest -q scripts/report compiler/tests
make lint test                              # full suite, as usual
```

Also run the publish dry run (`.publish/clean_copy.sh --dry-run`) before
publishing, then republish.

Suggested commit message:

```
docs: restructure README for architecture/compiler readers

Lead with performance, the compiler and the performance model; move the
full performance, verification, FPGA/ASIC and waveform sections into
docs/PERFORMANCE.md, docs/VERIFICATION.md, docs/PPA.md and
docs/waveforms/README.md. Add scripts/report/readme_figures.py (flow
diagram, MVP vs double-buffering utilization chart from results/perf).
```

## Optional fix noticed while reviewing

The roofline plot `results/perf/be6f466_roofline.png` still has the title
"no DMA/compute overlap in the MVP", but it is the double-buffering run.
The title comes from `scripts/measure/plot_perf.py` (line ~114). Make the
title depend on the run (or drop the MVP note) and regenerate with
`python3 scripts/measure/plot_perf.py results/perf/be6f466.csv`. The
bert_proj/bert_ffn_down labels on that plot also overlap.

## After that

Follow `GITHUB_SETUP.md` (About, topics, social preview, v1.0 release, pin).
