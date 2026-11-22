#!/usr/bin/env bash
# Run the RTL tests twice with the same SYSARRAY_SEED and check that the
# seed-dependent log lines (seed, and per-test stimulus summaries) are identical.
# Usage: bash scripts/check_repro.sh [seed]   (default seed 1)
# REPRO_PATHS selects the testbenches (default: a fast subset that covers every
# seeding path: the shared RNG helpers, a parameterized block, the controller and
# the compiler-driven flow). Use REPRO_PATHS=tb for the whole suite.
set -euo pipefail
seed="${1:-1}"
paths="${REPRO_PATHS:-tb/reg tb/pe tb/top tb/campaign}"
PYTHON="${PYTHON:-python3}"
out="$(mktemp -d)"
trap 'rm -r "$out"' EXIT

for i in 1 2; do
  SYSARRAY_SEED="$seed" "$PYTHON" -m pytest $paths -q -s -p no:cacheprovider >"$out/run$i.log" 2>&1
  # Keep only lines that depend on the seed; drop timestamps and sim times.
  grep -oE "SYSARRAY_SEED=[0-9]+( salt='[^']*')?|W=[0-9]+ D=[0-9]+: [0-9]+ valid samples checked" \
    "$out/run$i.log" >"$out/run$i.key"
done

lines=$(wc -l <"$out/run1.key")
if [ "$lines" -eq 0 ]; then
  echo "check_repro: no seed lines found in the log"; exit 1
fi
if diff -q "$out/run1.key" "$out/run2.key" >/dev/null; then
  echo "check_repro: OK, seed $seed, $lines seed-dependent lines identical across two runs"
  grep "valid samples checked" "$out/run1.key" | sort | uniq
else
  echo "check_repro: MISMATCH between runs"; diff "$out/run1.key" "$out/run2.key"; exit 1
fi
