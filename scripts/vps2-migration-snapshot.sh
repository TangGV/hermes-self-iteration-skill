#!/usr/bin/env bash
# Create a root-only VPS2 migration archive without stopping production services.
# Secrets are intentionally included in the archive; do not upload it to Git/chat.
set -euo pipefail
umask 077

BASE=/root/migration-snapshots
STAMP="vps2-$(date +%Y%m%d-%H%M%S)"
STAGE="$BASE/.${STAMP}.stage"
PAYLOAD="$STAGE/payload"
ARCHIVE="$BASE/${STAMP}.tar.gz"
TMP_ARCHIVE="$ARCHIVE.tmp"
MANIFEST="$BASE/${STAMP}.manifest.txt"
CHECKSUMS="$BASE/${STAMP}.SHA256SUMS"
ARCHIVE_SHA="$ARCHIVE.sha256"
MIN_AVAILABLE_KB=3500000

say() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
fail() { say "ERROR: $*" >&2; exit 1; }
backup_sqlite() {
  local src="$1" dst="$2"
  [ -f "$src" ] || fail "SQLite source missing: $src"
  mkdir -p "$(dirname "$dst")"
  python3 -c 'import os,sqlite3,sys; src,dst=sys.argv[1:3]; s=sqlite3.connect("file:"+src+"?mode=ro",uri=True); d=sqlite3.connect(dst); s.backup(d); d.close(); s.close()' "$src" "$dst"
  python3 -c 'import sqlite3,sys; db=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); r=db.execute("pragma quick_check").fetchone()[0]; db.close(); print(r); raise SystemExit(0 if r=="ok" else 1)' "$dst" >/dev/null
}

[ "$(id -u)" -eq 0 ] || fail 'run as root'
mkdir -p "$BASE"
chmod 700 "$BASE"
AVAILABLE_KB=$(df -Pk / | awk 'NR==2 {print $4}')
[ "${AVAILABLE_KB:-0}" -ge "$MIN_AVAILABLE_KB" ] || fail "need >=${MIN_AVAILABLE_KB} KiB free; have ${AVAILABLE_KB:-0} KiB"

rm -rf "$STAGE"
mkdir -p "$PAYLOAD/assets" "$PAYLOAD/metadata"
trap 'rm -rf "$STAGE" "$TMP_ARCHIVE"' EXIT

say 'capturing selected configuration, code, static assets, and non-live data files'
# Preserve the current path topology beneath payload/. Exclude rebuildable dependencies,
# transient log streams, and live SQLite files replaced with online backups below.
tar -C / \
  --exclude='root/data-collection-center/app/node_modules' \
  --exclude='root/data-collection-center/app/.venv' \
  --exclude='root/data-collection-center/app/.pytest_cache' \
  --exclude='root/data-collection-center/app/.hermes_upload_tmp' \
  --exclude='root/data-collection-center/app/web-next/node_modules' \
  --exclude='root/data-collection-center/app/web-next/.next' \
  --exclude='root/data-collection-center/app/data/collector.db' \
  --exclude='root/data-collection-center/app/data/collector.db-*' \
  --exclude='root/nodeseek-crawler/.venv' \
  --exclude='root/nodeseek-crawler/__pycache__' \
  --exclude='root/nodeseek-crawler/logs' \
  --exclude='root/trafficlens-debug-proxy/*.jsonl' \
  --warning=no-file-changed \
  -cpf - \
  etc/nginx \
  etc/systemd/system \
  etc/mihomo \
  etc/letsencrypt \
  usr/local/etc/xray \
  usr/local/bin/mihomo \
  usr/local/bin/xray \
  root/.ssh/authorized_keys \
  root/new-api/docker-compose.local.yml \
  root/cliproxyapi \
  root/.cli-proxy-api \
  root/cpa-usage-keeper/env.list \
  root/cursor-cpa-compat \
  root/subapi-cursor-compat \
  root/subapi-image-compat \
  root/trafficlens-debug-proxy \
  root/data-collection-center \
  root/nodeseek-crawler \
  root/ai-ops-control-center \
  root/aigcfast-static \
  opt/subapi-image-demo \
  root/.hermes/config.yaml \
  root/.hermes/.env \
  root/.hermes/cron \
  root/.hermes/scripts \
  root/.hermes/skills \
  root/.hermes/memories \
  root/AGENTS.md \
  root/VPS_OPERATIONS_LOG.md \
  root/VPS2_MIGRATION_RUNBOOK.md \
  root/VPS2_MIGRATION_RESTORE.sh \
  root/VPS2_MIGRATION_SNAPSHOT.sh \
  | tar -C "$PAYLOAD" -xpf -

say 'creating consistent online SQLite backups'
backup_sqlite /root/new-api/data/one-api.db "$PAYLOAD/root/new-api/data/one-api.db"
backup_sqlite /root/cpa-usage-keeper/data/app.db "$PAYLOAD/root/cpa-usage-keeper/data/app.db"
backup_sqlite /root/data-collection-center/app/data/collector.db "$PAYLOAD/root/data-collection-center/app/data/collector.db"

say 'saving exact current Docker images'
docker image save -o "$PAYLOAD/assets/docker-images.tar" \
  calciumion/new-api:latest \
  ghcr.io/willxup/cpa-usage-keeper:latest

say 'writing non-secret metadata'
{
  echo "source_timestamp=$(date -Is)"
  echo "hostname=$(hostname)"
  echo "os=$(tr '\n' ' ' < /etc/os-release | sed 's/"//g')"
  echo
  echo '## versions'
  nginx -v 2>&1 || true
  node --version || true
  npm --version || true
  python3 --version || true
  docker --version || true
  docker-compose --version || true
  /root/cliproxyapi/cli-proxy-api version 2>&1 | head -1 || true
  /usr/local/bin/xray version 2>&1 | head -1 || true
  /usr/local/bin/hermes --version 2>&1 | head -1 || true
  echo
  echo '## selected service state'
  systemctl is-active nginx docker mihomo cliproxyapi cursor-cpa-compat subapi-cursor-compat subapi-image-compat trafficlens-cpa-debug xray data-collection-center subapi-image-demo ai-ops-control-center hermes-gateway || true
  echo
  echo '## ports'
  ss -ltnp || true
  echo
  echo '## docker images'
  docker image inspect calciumion/new-api:latest ghcr.io/willxup/cpa-usage-keeper:latest --format '{{.RepoTags}} {{.Id}} {{.Created}} {{.Size}}' || true
  echo
  echo '## source db quick checks'
  python3 -c 'import sqlite3; paths=["/root/new-api/data/one-api.db","/root/cpa-usage-keeper/data/app.db","/root/data-collection-center/app/data/collector.db"]; [print(p, sqlite3.connect("file:"+p+"?mode=ro",uri=True).execute("pragma quick_check").fetchone()[0]) for p in paths]'
} > "$PAYLOAD/metadata/source-state.txt"

printf '%s\n' \
  'This archive is secret-bearing and root-only.' \
  'It contains raw configurations, credential stores, TLS material, and application data.' \
  'Do not commit, attach to chat, expose over HTTP, or extract onto an untrusted machine.' \
  'Use /root/VPS2_MIGRATION_RUNBOOK.md and /root/VPS2_MIGRATION_RESTORE.sh after transfer.' \
  > "$PAYLOAD/README-PRIVATE.txt"

say 'building compressed archive'
tar -C "$STAGE" -czf "$TMP_ARCHIVE" payload
gzip -t "$TMP_ARCHIVE"
mv "$TMP_ARCHIVE" "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE_SHA"
tar -tzf "$ARCHIVE" > "$MANIFEST"
(
  cd "$PAYLOAD"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "$CHECKSUMS"
chmod 600 "$ARCHIVE" "$ARCHIVE_SHA" "$MANIFEST" "$CHECKSUMS"
ln -sfn "$(basename "$ARCHIVE")" "$BASE/latest.tar.gz"
# Keep a regular portable checksum sidecar: scp follows the latest.tar.gz symlink,
# therefore this file must validate the destination filename, not the timestamped source name.
printf '%s  latest.tar.gz\n' "$(cut -d' ' -f1 "$ARCHIVE_SHA")" > "$BASE/latest.tar.gz.sha256"
chmod 600 "$BASE/latest.tar.gz.sha256"
ln -sfn "$(basename "$MANIFEST")" "$BASE/latest.manifest.txt"
ln -sfn "$(basename "$CHECKSUMS")" "$BASE/latest.SHA256SUMS"

ARCHIVE_BYTES=$(stat -c '%s' "$ARCHIVE")
say "snapshot complete: $ARCHIVE (${ARCHIVE_BYTES} bytes)"
say "checksum: $(cut -d' ' -f1 "$ARCHIVE_SHA")"
