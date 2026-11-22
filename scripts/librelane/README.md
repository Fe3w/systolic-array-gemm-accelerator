# SKY130 flow (LibreLane) for `sa_array`

`run.py` places and routes `sa_array` (S = 8 by default) on SkyWater SKY130
(`sky130A`, `sky130_fd_sc_hd`) with LibreLane and writes
`results/asic/sa_array_S<S>_<sha>_<period>ns.json`. `setup.sh` prepares the tools.

What is pinned:
- Image `ghcr.io/librelane/librelane:3.0.17` (OpenROAD, Yosys 0.62, Magic,
  Netgen, KLayout inside; the exact versions are recorded in every result file).
- PDK `sky130` version `8afc8346a57fe1ab7934ba5a6056ea8b43078e71` (the one
  LibreLane 3.0.17 pins), installed with `ciel` into `$PDK_ROOT`
  (default `~/.sysarray-pdk`, about 2.2 GB).

## Run (cloud session or a local machine with Docker)

```bash
bash scripts/librelane/setup.sh          # dockerd if needed, image, PDK (idempotent)
python3 scripts/librelane/run.py --S 8 --period 20
```

or `make asic PERIOD=20` (runs both). One S = 8 run takes about 75 minutes on
4 cores. The full run directory (GDS, DEF, logs) stays in `build/asic/`; only
the summary, the metrics, the resolved config and the post-route STA summary
are committed under `results/asic/`.

## Local machine (Ubuntu 24.04), from a clean clone

```bash
sudo apt-get update && sudo apt-get install -y docker.io git python3
sudo usermod -aG docker "$USER" && newgrp docker
git clone https://github.com/Fe3w/systolic-array-gemm-accelerator.git sysarray && cd sysarray
bash scripts/librelane/setup.sh
python3 scripts/librelane/run.py --S 8 --period 20
```

## Notes

- Why Docker: the image carries every tool at a tested version; the
  alternative is LibreLane's Nix flake (`nix run github:librelane/librelane`),
  which needs GitHub access that cloud sessions do not have.
- PDK download: `ciel`'s default source, `fossi-foundation.github.io/ciel-releases`,
  redirects to `www-archive.fossi-foundation.org`; `setup.sh` uses that host
  directly (`CIEL_SOURCE` overrides it).
- `sa_core` is out of scope: without SRAM macros its 256-row buffers would be
  synthesized as flip-flops, so its area would not represent the design.
- The ECP5-only define `SA_ECP5_DSP` is not set here, so the PE's product
  register is an ordinary flip-flop.
