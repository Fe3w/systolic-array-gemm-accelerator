# scripts/synth/

FPGA synthesis flow (Yosys + nextpnr), added in M7. Proposed target: Lattice ECP5
(decision D-006). Outputs a summary JSON (LUTs, FFs, DSPs, BRAM, Fmax) plus raw
reports into `results/synth/`.
