#!/usr/bin/env bash
# Prepare the SKY130 ASIC flow for scripts/librelane/run.py (M12). Idempotent.
#
#   1. a Docker daemon (cloud sessions have the CLI but no running daemon),
#   2. the LibreLane image (OpenROAD, Yosys, Magic, Netgen, KLayout inside),
#   3. the SKY130 PDK version LibreLane pins, fetched with ciel into $PDK_ROOT.
#
# ciel's default source (fossi-foundation.github.io/ciel-releases) redirects to
# www-archive.fossi-foundation.org; using that host directly also works where
# github.com release downloads are blocked (cloud sessions).
# Env: LIBRELANE_IMAGE, PDK_ROOT (default ~/.sysarray-pdk), CIEL_SOURCE.
set -euo pipefail

IMAGE="${LIBRELANE_IMAGE:-ghcr.io/librelane/librelane:3.0.17}"
PDK_ROOT="${PDK_ROOT:-$HOME/.sysarray-pdk}"
PDK_VERSION="8afc8346a57fe1ab7934ba5a6056ea8b43078e71"  # LibreLane 3.0.17 pdk_hashes.yaml
CIEL_SOURCE="${CIEL_SOURCE:-static-web:https://www-archive.fossi-foundation.org/ciel-releases}"
PROXY_CA="/root/.ccr/ca-bundle.crt"  # cloud sessions: TLS-intercepting proxy CA

log() { echo "[librelane-setup] $*"; }

if ! docker info >/dev/null 2>&1; then
  log "starting dockerd"
  (nohup dockerd >/tmp/dockerd.log 2>&1 &)
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 || { log "dockerd did not start (see /tmp/dockerd.log)"; exit 1; }
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  log "pulling $IMAGE"
  docker pull -q "$IMAGE"
fi

if [ ! -d "$PDK_ROOT/ciel/sky130/versions/$PDK_VERSION" ]; then
  log "fetching SKY130 PDK $PDK_VERSION into $PDK_ROOT"
  mkdir -p "$PDK_ROOT"
  args=(--rm --network host -v "$PDK_ROOT:/pdk")
  if [ -f "$PROXY_CA" ]; then
    # httpx in the image trusts the image's CA bundle only: mount the proxy CA over it.
    certifi=$(docker run --rm "$IMAGE" python3 -c "import certifi; print(certifi.where())")
    args+=(-v "$PROXY_CA:$certifi:ro" -e HTTPS_PROXY -e https_proxy="${HTTPS_PROXY:-}")
  fi
  docker run "${args[@]}" "$IMAGE" ciel enable --pdk-root /pdk --pdk-family sky130 \
    --data-source "$CIEL_SOURCE" "$PDK_VERSION"
fi
log "ready: image $IMAGE, PDK_ROOT=$PDK_ROOT"
