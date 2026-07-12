#!/usr/bin/env bash
# Guarded restore helper for a NEW/approved VPS only.
# It never changes DNS and refuses to replace existing New API / Keeper containers.
set -euo pipefail

ARCHIVE=''
APPLY=0
WORK=''

usage() {
  printf '%s\n' \
    'Usage: VPS2_MIGRATION_RESTORE.sh --archive /root/migration-snapshots/latest.tar.gz --apply' \
    '' \
    'This restores secret-bearing VPS2 payload files onto the current host, loads saved images,' \
    'rebuilds dependency trees, and starts the production units. It does NOT change DNS or start Hermes.'
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
cleanup() { [ -n "$WORK" ] && rm -rf "$WORK"; }
trap cleanup EXIT

while [ "$#" -gt 0 ]; do
  case "$1" in
    --archive) ARCHIVE="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[ "$APPLY" -eq 1 ] || { usage; fail 'refusing to run without explicit --apply'; }
[ "$(id -u)" -eq 0 ] || fail 'run as root'
[ -f "$ARCHIVE" ] || fail "archive not found: $ARCHIVE"
command -v docker >/dev/null || fail 'Docker must be installed before restore'
command -v nginx >/dev/null || fail 'nginx must be installed before restore'
command -v node >/dev/null || fail 'Node.js must be installed before restore'
command -v npm >/dev/null || fail 'npm must be installed before restore'
command -v python3 >/dev/null || fail 'Python 3 must be installed before restore'

for container in new-api cpa-usage-keeper; do
  if docker container inspect "$container" >/dev/null 2>&1; then
    fail "container already exists: $container. Back it up/remove it deliberately; this helper will not overwrite it."
  fi
done

SIDECAR="${ARCHIVE}.sha256"
if [ -f "$SIDECAR" ]; then
  printf 'Verifying archive checksum...\n'
  (
    cd "$(dirname "$ARCHIVE")"
    sha256sum -c "$(basename "$SIDECAR")"
  ) || fail 'archive SHA-256 verification failed'
else
  printf 'WARNING: no sidecar %s; continuing only because --apply was explicit.\n' "$SIDECAR" >&2
fi

WORK=$(mktemp -d /root/vps2-restore.XXXXXX)
tar -xzf "$ARCHIVE" -C "$WORK"
PAYLOAD="$WORK/payload"
[ -d "$PAYLOAD" ] || fail 'archive does not contain payload/'
[ -f "$PAYLOAD/assets/docker-images.tar" ] || fail 'saved Docker image bundle missing'

printf 'Copying preserved system/application paths...\n'
for top in etc root opt usr; do
  if [ -d "$PAYLOAD/$top" ]; then
    mkdir -p "/$top"
    cp -a "$PAYLOAD/$top/." "/$top/"
  fi
done
chmod 700 /root/migration-snapshots 2>/dev/null || true
chmod 700 /root/VPS2_MIGRATION_RESTORE.sh /root/VPS2_MIGRATION_SNAPSHOT.sh 2>/dev/null || true

printf 'Loading exact Docker images...\n'
docker load -i "$PAYLOAD/assets/docker-images.tar"

if command -v docker-compose >/dev/null; then
  COMPOSE=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  fail 'docker-compose or docker compose plugin is required'
fi

printf 'Rebuilding app dependency trees...\n'
(
  cd /root/data-collection-center/app
  npm ci
)
(
  cd /opt/subapi-image-demo
  npm ci --omit=dev
)
(
  cd /root/nodeseek-crawler
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
)

printf 'Validating restored SQLite stores...\n'
python3 - <<'PY'
import sqlite3
paths = [
    '/root/new-api/data/one-api.db',
    '/root/cpa-usage-keeper/data/app.db',
    '/root/data-collection-center/app/data/collector.db',
]
for path in paths:
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    result = db.execute('pragma quick_check').fetchone()[0]
    db.close()
    print(path, result)
    if result != 'ok':
        raise SystemExit(f'SQLite integrity failure: {path}')
PY

printf 'Starting services in dependency order...\n'
systemctl daemon-reload
systemctl enable --now mihomo.service
"${COMPOSE[@]}" -f /root/new-api/docker-compose.local.yml up -d new-api

docker run -d \
  --name cpa-usage-keeper \
  --restart unless-stopped \
  --env-file /root/cpa-usage-keeper/env.list \
  -p 8080:8080 \
  -v /root/cpa-usage-keeper/data:/data \
  ghcr.io/willxup/cpa-usage-keeper:latest

systemctl enable --now \
  cliproxyapi.service \
  cursor-cpa-compat.service \
  subapi-cursor-compat.service \
  subapi-image-compat.service \
  trafficlens-cpa-debug.service \
  xray.service \
  data-collection-center.service \
  subapi-image-demo.service \
  ai-ops-control-center.service \
  aigcfast-static.service

nginx -t
systemctl enable --now nginx.service
systemctl enable --now dc-forum-collect.timer dc-forum-detail-backfill.timer

# Deliberately NOT enabled: hermes-gateway.service, subapi-image-demo-candidate.service,
# and the orphaned /tmp/mihomo-tw-test process.

printf '\nRestore completed locally. Next: execute the acceptance section in VPS2_MIGRATION_RUNBOOK.md, then make only approved DNS changes.\n'
