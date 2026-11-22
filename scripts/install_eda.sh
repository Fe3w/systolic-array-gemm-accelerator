#!/usr/bin/env bash
# Install the EDA tools SysArray needs (decision D-013).
#
# Default method (works in sandboxed cloud environments, where GitHub release
# downloads are blocked):
#   * Verilator >= 5.036 and Yosys from conda-forge, installed with a
#     throw-away micromamba into $EDA_PREFIX (default /opt/eda).
#   * nextpnr-ecp5 from PyPI (yowasp-nextpnr-ecp5, WebAssembly build), used
#     from M7 on. Its command is `yowasp-nextpnr-ecp5`.
# Alternative (EDA_METHOD=oss-cad-suite): the OSS CAD Suite GitHub release,
#   for machines that can reach GitHub releases (this was the M1 default).
#
# Idempotent: exits quickly when Verilator is already installed in the prefix.
# All output goes to stderr so this script is safe to call from a session-start hook.
#
# Environment:
#   EDA_PREFIX       install directory (default /opt/eda, or $HOME/.local/eda
#                    if /opt is not writable)
#   EDA_METHOD       conda (default) | oss-cad-suite
#   OSS_CAD_VERSION  release tag for EDA_METHOD=oss-cad-suite (default: latest)
set -euo pipefail
exec 1>&2

method="${EDA_METHOD:-conda}"
if [ -n "${EDA_PREFIX:-}" ]; then
  prefix="$EDA_PREFIX"
elif [ -w /opt ] || [ "$(id -u)" = "0" ]; then
  prefix=/opt/eda
else
  prefix="$HOME/.local/eda"
fi

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "[install_eda] Only Linux x86_64 is handled here. Install the tools manually."
  exit 1
fi

install_nextpnr() {
  if command -v yowasp-nextpnr-ecp5 >/dev/null 2>&1; then
    return 0
  fi
  echo "[install_eda] Installing yowasp-nextpnr-ecp5 from PyPI"
  python3 -m pip install -q yowasp-nextpnr-ecp5 \
    || python3 -m pip install -q --break-system-packages yowasp-nextpnr-ecp5 \
    || echo "[install_eda] yowasp-nextpnr-ecp5 install failed (only needed from M7)"
}

install_conda() {
  if [ -x "$prefix/bin/verilator" ]; then
    echo "[install_eda] Verilator already present in $prefix"
    return 0
  fi
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -r "$tmp"' RETURN
  echo "[install_eda] Downloading micromamba"
  curl -fsSL --retry 3 -o "$tmp/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
  tar -xjf "$tmp/mm.tar.bz2" -C "$tmp" bin/micromamba
  echo "[install_eda] Creating $prefix with verilator>=5.036 and yosys from conda-forge"
  MAMBA_ROOT_PREFIX="$tmp/root" "$tmp/bin/micromamba" create -y -q -p "$prefix" \
    -c conda-forge "verilator>=5.036" yosys
  "$prefix/bin/verilator" --version
}

install_oss_cad_suite() {
  if [ -x "$prefix/bin/verilator" ]; then
    echo "[install_eda] OSS CAD Suite already present at $prefix"
    return 0
  fi
  local api url tmp
  api="https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases"
  if [ -n "${OSS_CAD_VERSION:-}" ]; then api="$api/tags/$OSS_CAD_VERSION"; else api="$api/latest"; fi
  echo "[install_eda] Looking up release: $api"
  url="$(curl -fsSL "$api" | python3 -c '
import json, sys
for asset in json.load(sys.stdin).get("assets", []):
    name = asset["name"]
    if name.startswith("oss-cad-suite-linux-x64-") and name.endswith(".tgz"):
        print(asset["browser_download_url"])
        break
')"
  if [ -z "$url" ]; then
    echo "[install_eda] Could not find a linux-x64 .tgz asset in the release."
    return 1
  fi
  tmp="$(mktemp -d)"
  trap 'rm -r "$tmp"' RETURN
  curl -fL --retry 3 --retry-delay 5 -o "$tmp/oss-cad-suite.tgz" "$url"
  tar -xzf "$tmp/oss-cad-suite.tgz" -C "$tmp"
  mkdir -p "$(dirname "$prefix")"
  if [ -e "$prefix" ]; then mv "$prefix" "$prefix.old.$$"; fi
  mv "$tmp/oss-cad-suite" "$prefix"
  "$prefix/bin/verilator" --version
}

case "$method" in
  conda) install_conda ;;
  oss-cad-suite) install_oss_cad_suite ;;
  *) echo "[install_eda] Unknown EDA_METHOD=$method (use conda or oss-cad-suite)"; exit 1 ;;
esac
install_nextpnr
echo "[install_eda] Done. Add $prefix/bin to PATH."
