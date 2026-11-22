# GitHub settings for SysArray (things outside the files)

Do these on github.com after pushing the new README. Each takes about a minute.

## 1. About box (repo page → gear icon next to "About")

**Description** (max ~350 chars; this is what shows in search results and on your profile):

> int8 systolic-array GEMM accelerator in SystemVerilog with its own Python tiling compiler. 8×8 weight-stationary array, 0.78–0.82 PE utilization on BERT/ResNet-50 3×3 layers, cycle-exact performance model, verified with cocotb vs NumPy, 92.89 MHz on ECP5, placed and routed on SKY130.

**Website:** leave empty for now; put the demo video link here once it's recorded.

**Topics** (paste one by one):

```
systolic-array  hardware-accelerator  systemverilog  gemm  matrix-multiplication
cocotb  verilator  fpga  ecp5  asic  sky130  openroad  yosys
computer-architecture  ml-accelerator  tiling-compiler  hardware-software-codesign
```

Untick **Releases**, **Packages** and **Deployments** in "Include in the home
page" if you don't use them. Empty sections make the page look unfinished.
(Keep Releases ticked if you do step 3.)

## 2. Social preview image

Settings → General → Social preview → Upload `social_preview.png` (1280 × 640,
in this kit). This is the card that shows when the link is pasted into
LinkedIn, Slack or an email. Every number on it is from `results/` and matches
the README.

## 3. Release v1.0

Releases → "Draft a new release" → tag `v1.0` on `main`, title
**SysArray v1.0**, body:

```markdown
First complete version of SysArray.

- 8 × 8 weight-stationary int8 systolic array in synthesizable SystemVerilog, with DMA, buffers, int32 accumulator and a command controller with double buffering
- Python tiling compiler (two loop orders, overlap scheduling) and a cycle-exact performance model (measured = predicted in 16 / 16 runs)
- PE utilization 0.78–0.82 on BERT and ResNet-50 3×3 layers (from 0.43–0.45 in the first version)
- Verified with cocotb + Verilator against NumPy: 1,000 / 1,000 random compiler-driven GEMMs
- Lattice ECP5: full accelerator at 92.89 MHz; SkyWater SKY130: array placed and routed, 1.053 mm² core (timing sign-off open, see docs/PPA.md)

Sources for every number: README and docs/RESULTS.md.
```

A tagged release tells a reviewer "this is finished and versioned", not "work
in progress".

## 4. Pin it

Your profile → "Customize your pins" → pin this repo (first position if it's
your strongest project).

## 5. CI badge check

After pushing, open the Actions tab. The badge at the top of the README shows
the latest `ci` workflow run. If the run is red, either fix it or remove the
badge line. A red badge is worse than none. (I couldn't check your Actions
status from here.)

## 6. Commit history (for future projects)

The public repo has one commit because it is a clean copy of the development
repo (D-034). That's fine, and it is documented. Don't backdate fake commits
to make it look iterative. If someone asks, the decision log
(`docs/DECISIONS.md`) and the commit hashes in `results/` show how the design
evolved. For the next project, publish the real history.
