#!/usr/bin/env bash
# Print tool versions and fail if a required tool is missing or too old.
# Required: Verilator >= 5.036 (cocotb 2.x), Python packages cocotb>=2, numpy, pytest.
# Optional (warn only until the milestone that needs them): yosys, nextpnr-ecp5
# (native or yowasp-nextpnr-ecp5).
set -uo pipefail

PYTHON="${PYTHON:-python3}"
fail=0

version_ge() { # version_ge A B  -> true if A >= B
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

echo "== Tools =="
# Every verilator on PATH, in PATH order: the first one is the one make uses.
mapfile -t verilators < <(type -ap verilator 2>/dev/null | awk '!seen[$0]++')
if [ "${#verilators[@]}" -gt 0 ]; then
  first="${verilators[0]}"
  v="$("$first" --version | awk '{print $2}')"
  if version_ge "$v" "5.036"; then
    echo "OK   verilator $v ($first)"
  else
    echo "FAIL verilator $v at $first (need >= 5.036 for cocotb 2.x)"
    for other in "${verilators[@]:1}"; do
      ov="$("$other" --version 2>/dev/null | awk '{print $2}')"
      if version_ge "$ov" "5.036"; then
        echo "     a usable verilator $ov is at $other, but $first comes first on PATH"
      fi
    done
    if [ "$first" = "/usr/bin/verilator" ]; then
      echo "     $first is Ubuntu's package: sudo apt remove verilator (docs/LOCAL_SETUP.md section 9)"
    else
      echo "     install a newer one: docs/LOCAL_SETUP.md section 5"
    fi
    fail=1
  fi
else
  echo "FAIL verilator not found (docs/LOCAL_SETUP.md section 5: OSS CAD Suite or bash scripts/install_eda.sh, then add its bin/ to PATH)"
  fail=1
fi

if command -v yosys >/dev/null 2>&1; then
  echo "OK   yosys $(yosys -V 2>&1 | head -n1 | cut -c1-40) ($(command -v yosys))"
else
  echo "WARN yosys not found (needed from M7)"
fi

# nextpnr-ecp5: native binary (OSS CAD Suite, CI) or the PyPI WebAssembly build
# (yowasp-nextpnr-ecp5, cloud sessions, D-013). Presence only: the first yowasp
# run compiles the WebAssembly module and is slow.
if command -v nextpnr-ecp5 >/dev/null 2>&1; then
  echo "OK   nextpnr-ecp5 (native, $(command -v nextpnr-ecp5))"
elif command -v yowasp-nextpnr-ecp5 >/dev/null 2>&1; then
  echo "OK   nextpnr-ecp5 (yowasp-nextpnr-ecp5)"
else
  echo "WARN nextpnr-ecp5 not found (only for make synth; OSS CAD Suite ships it, option B installs yowasp-nextpnr-ecp5)"
fi

for tool in make g++ git; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "OK   $tool"
  else
    echo "FAIL $tool not found"
    fail=1
  fi
done

echo "== Python ($PYTHON) =="
"$PYTHON" - <<'PY' || fail=1
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version
ok = True
print(f"OK   python {sys.version.split()[0]}")
for name, minimum in [("cocotb", "2.0"), ("numpy", None), ("pytest", None)]:
    try:
        version = pkg_version(name)
    except PackageNotFoundError:
        print(f"FAIL {name} not installed (pip install -r requirements.txt)")
        ok = False
        continue
    if minimum and int(version.split(".")[0]) < int(minimum.split(".")[0]):
        print(f"FAIL {name} {version} (need >= {minimum})")
        ok = False
    else:
        print(f"OK   {name} {version}")
sys.exit(0 if ok else 1)
PY

if [ "$fail" -ne 0 ]; then
  echo "check_env: FAILED"
  exit 1
fi
echo "check_env: OK"
