# VPS2 Full Migration Runbook

> **Purpose:** recreate the current VPS2 forwarding, services, data, and safe runtime configuration on a replacement server without relying on stale chat history.
> **Source inspected:** `root@62.106.70.67` / `GreenCloud` / Debian 12, 2026-07-12 CST.
> **Secret policy:** this file is intentionally redacted. The root-only snapshot contains the raw configuration, OAuth/auth JSON, TLS keys, Xray credentials, API keys, cookies, and DB data. Never place that archive or its contents in Git, Telegram, a ticket, or a public web root.

---

## 1. Snapshot / restore assets

| Asset | Purpose | Access policy |
|---|---|---|
| `/root/migration-snapshots/latest.tar.gz` | Full private migration archive | `root:root`, mode `0600` |
| `/root/migration-snapshots/latest.tar.gz.sha256` | Archive integrity check | `0600` |
| `/root/migration-snapshots/latest.manifest.txt` | Archive file list | `0600` |
| `/root/migration-snapshots/latest.SHA256SUMS` | Payload file checksums | `0600` |
| `/root/VPS2_MIGRATION_RESTORE.sh` | Guarded future-host restore helper | no DNS cutover by itself |
| `/root/VPS2_MIGRATION_SNAPSHOT.sh` | Rebuilds a consistent private snapshot | uses SQLite online backup |

The archive includes current service configuration, TLS material, app source/data/static assets, raw auth/config data, and Docker images. It intentionally excludes rebuildable dependency trees (`node_modules`, Python virtualenvs) and high-volume transient runtime logs/caches. Package locks, requirements, runnable `dist`, source, static files, and live data are retained.

### Completed snapshot receipt

| Field | Recorded value |
|---|---|
| Created on source | `2026-07-12T20:59:50+08:00` → `21:02:44+08:00` |
| Timestamped archive | `/root/migration-snapshots/vps2-20260712-205950.tar.gz` |
| Archive size | `702,171,796` bytes |
| SHA-256 | `6adf913da96bb1d552e597730ec4aaaee58216548d5ecee629a934dab300ef1f` |
| Source verification | `sha256sum -c`, `gzip -t`, required payload path listing: passed |
| Off-host private copy | `C:\Users\t\VPS2-migration-snapshots\latest.tar.gz` + portable SHA sidecar; SHA-256 verified |

### Current data baseline (use this to validate a recovered copy)

| Store | Live path | Snapshot baseline / integrity |
|---|---|---|
| New API | `/root/new-api/data/one-api.db` | 47,517,696 bytes; `quick_check=ok`; 29 users, 22 tokens, 10 channels, 99 abilities, 40,773 logs |
| DC collector | `/root/data-collection-center/app/data/collector.db` | 189,194,240 bytes; `quick_check=ok`; 62,328 items, 7,149 details |
| CPA Usage Keeper | `/root/cpa-usage-keeper/data/app.db` | active SQLite/WAL store; snapshot uses a consistent online backup |

### Archive transfer / integrity

On the current source, copy the **latest** archive plus its SHA sidecar to a private location before any destructive source action:

```bash
scp root@62.106.70.67:/root/migration-snapshots/latest.tar.gz \
  /private/backup/location/
scp root@62.106.70.67:/root/migration-snapshots/latest.tar.gz.sha256 \
  /private/backup/location/
cd /private/backup/location
sha256sum -c latest.tar.gz.sha256
```

On a future host, copy those two files to `/root/migration-snapshots/`; then use the guarded helper:

```bash
chmod 700 /root/VPS2_MIGRATION_RESTORE.sh
/root/VPS2_MIGRATION_RESTORE.sh \
  --archive /root/migration-snapshots/latest.tar.gz \
  --apply
```

The helper deliberately does **not** edit Cloudflare DNS, start Hermes Gateway, or remove pre-existing same-name Docker containers.

---

## 2. Source platform and exact runtime versions

| Item | Observed value |
|---|---|
| OS / kernel | Debian 12 (bookworm), `6.1.0-44-amd64` |
| VPS resources at capture | 3.8 GiB RAM; root disk 21G with ~5.3G free |
| Nginx | `1.22.1` |
| Docker | `20.10.24+dfsg1`; legacy `docker-compose 1.29.2` available |
| Node / npm | `v20.20.2` / `10.8.2` |
| Python | `3.11.2` |
| CLIProxyAPI | `7.2.58`, commit `26d45fd4` |
| Xray | `26.3.27` |
| Hermes CLI | `0.16.0` |
| New API image | `calciumion/new-api@sha256:6da2278e7f28109043375e373546efdfb96d9a60d82a46f039d0a81499ec8cd3` |
| CPA Keeper image | `ghcr.io/willxup/cpa-usage-keeper@sha256:7cc06e00ea909c1810e14c23d2edf639d9209da5c5cb01fa0d3445b758b16cb7` |

The live compose file uses `:latest`; do not repull blindly during a clone. Load the image saved in the snapshot first, then start the preserved compose file.

---

## 3. Network / ports / exposure

### Preserve behavior on a clone

| Port | Bind at capture | Owner | Migration action |
|---:|---|---|---|
| 22 | public | `sshd` | bootstrap the owner’s existing SSH key before changing anything |
| 80, 443 | public | nginx | copy `/etc/nginx`, certificate material, then verify forced-SNI before DNS |
| 3000 | public via Docker | New API | preserve only if parity is required; current container publishes it directly |
| 8080 | public via Docker | CPA Usage Keeper | preserve only if parity is required; contains an auth surface |
| 8317 | public | CLIProxyAPI | current direct CPA API / management listener |
| 8326 | loopback | `cursor-cpa-compat` | direct Cursor-to-CPA bridge |
| 8327 | loopback | `subapi-cursor-compat` | Cursor-to-New API bridge |
| 8328 | loopback | `subapi-image-compat` | image / responses compatibility bridge |
| 8330 | loopback | TrafficLens | relay auxiliary listener |
| 18888 | public | TrafficLens relay | forwards to local CPA `8317` |
| 18084 | public | DC panel | Basic Auth application endpoint |
| 8798 | loopback | Image demo UI | reached only through nginx `image` vhost |
| 8799 | public | AI Ops Control Center | also reached via nginx `/dashboard/` |
| 3021 | public | AIGC static server | reached by preconfigured apex HTTP vhost |
| 7890, 7891, 9090 | loopback | Mihomo | `7890` mixed proxy; `7891` SOCKS; `9090` controller |
| 38443 | public | Xray | VLESS + REALITY inbound |

No custom UFW policy was observed; the host input policy is permissive and Docker publishes `3000` / `8080` directly. A replacement server with a provider firewall must allow the ports above **only when preserving current behavior is intended**. Harden exposure only after parity validation, not midway through a cutover.

### Do **not** migrate as production

- `/tmp/mihomo-tw-test`, PID inherited by `init`, loopback `17890` / `19090`: leftover Mihomo test instance.
- `subapi-image-demo-candidate.service`: transient failed candidate; it exited because `127.0.0.1:8799` was already occupied. The real image UI is `subapi-image-demo.service` on `8798`.
- `hermes-gateway.service`: currently `failed`; do not autostart on a clone until a separate bot token / Telegram reachability decision is made.

---

## 4. Nginx forwarding — exact logical route map

### Important active-file trap

The current live multi-host file is a **regular file**:

```text
/etc/nginx/sites-enabled/api2.aigcfast.com
```

It is no longer a symlink. `sites-available/api2.aigcfast.com` is a different older file. Copy and edit the enabled file (or consciously restore the symlink model), then:

```bash
nginx -t && systemctl reload nginx
```

### `api.aigcfast.com` and forced `api2.aigcfast.com` vhost

| HTTPS path | Upstream | Notes |
|---|---|---|
| `/subapi/` | `http://127.0.0.1:3000/` | strips `/subapi/`; New API panel/API |
| `/v1/images/` | `http://127.0.0.1:3000` | images API route |
| `/cursor/` | `http://127.0.0.1:8326` | direct CPA Cursor bridge |
| `/tl/` | `http://127.0.0.1:18888` | TrafficLens relay/debug path |
| `/dashboard/` | `http://127.0.0.1:8799/` | strips prefix; AI Ops |
| `/datacenter/` | `http://127.0.0.1:18084/` | strips prefix; DC Basic Auth app |
| `/` | `http://127.0.0.1:8317` | CLIProxyAPI default/API/management |

The TLS server has `client_max_body_size 100m`, disabled proxy/request buffering, and 3600-second streaming timeouts on API/streaming routes.

### `subapi.aigcfast.com` vhost

| HTTPS path | Upstream | Notes |
|---|---|---|
| `/cursor/v2/` | `http://127.0.0.1:8326/cursor/v1/` | compatibility rewrite; preserve exact trailing-slash behavior |
| `/cursor/v1/` | `http://127.0.0.1:8327` | Responses-style Cursor payload normalization into New API chat flow |
| exact `/v1/responses` | `http://127.0.0.1:8328` | image compat sidecar; GET naturally returns 404, test POST with auth |
| all other paths | `http://127.0.0.1:3000` | New API / SubAPI |

This TLS server also has `client_max_body_size 100m`, buffering disabled, and long streaming timeouts. This is the previous fix for Cursor/Codex bodies larger than nginx’s default 1 MiB.

### `image.aigcfast.com` vhost

| HTTPS path | Upstream |
|---|---|
| `/v1/` | `http://127.0.0.1:8328` |
| `/api/` | `http://127.0.0.1:8798` |
| `/` | `http://127.0.0.1:8798` |

Port 80 has the same `/v1/ → 8328` split but otherwise points to `:3021`. Preserve the HTTPS block as the public image UI source.

### Prepared apex vhost

`aigcfast.com` and `www.aigcfast.com` have an **HTTP-only** vhost to `http://127.0.0.1:3021`. At the snapshot baseline, public DNS returned no A record and no TLS certificate existed. Only add DNS/certificates when explicitly moving that site.

---

## 5. DNS / TLS cutover boundary

| Hostname | Snapshot DNS A state | Cutover rule |
|---|---|---|
| `api.aigcfast.com` | `62.106.70.67` (VPS2) | move to a replacement only after vhost/API smoke passes |
| `subapi.aigcfast.com` | `62.106.70.67` (VPS2) | move with New API + sidecars + CPA parity |
| `image.aigcfast.com` | `62.106.70.67` (VPS2) | move with `8798` UI + `8328` sidecar |
| `api2.aigcfast.com` | `82.158.91.156` (VPS3/CN2) | **leave unchanged** unless requested |
| `subapi2.aigcfast.com` | `82.158.91.156` (VPS3/CN2) | **leave unchanged** |
| `subapi3.aigcfast.com` | `82.158.91.156` (VPS3/CN2) | **leave unchanged** |
| `aigcfast.com`, `www` | no A answer at capture | optional later site publication only |

Certificate inventory at capture:

| Certificate | Covered names | Renewal note |
|---|---|---|
| `api2.aigcfast.com` | `api2.aigcfast.com`, `api.aigcfast.com` | private key is in snapshot; reissue/renew after target DNS is valid |
| `subapi.aigcfast.com` | `subapi.aigcfast.com` | same |
| `image.aigcfast.com` | `image.aigcfast.com` | same |

Do not prematurely move an A record just to run HTTP-01. Pre-stage nginx and certificate material, smoke with `curl --resolve`, then perform the authorized DNS cutover. If reissuing is required, use the intended DNS/ACME method after the record is under control.

---

## 6. Service-specific configuration to carry forward

### New API / SubAPI

- Compose: `/root/new-api/docker-compose.local.yml`
- Data: `/root/new-api/data/one-api.db` (online SQLite snapshot)
- Bind mounts: `./data:/data`, `./logs:/app/logs`
- Container name: `new-api`; ports `3000:3000`; `host.docker.internal:host-gateway`
- Current `NODE_NAME=subapi`; current runtime has **no** `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, or `NO_PROXY` environment variables.
- Do **not** resurrect stale proxy environment from historical log entries. It caused `fetch_models` errors when a Docker host gateway proxy was unavailable.

### CLIProxyAPI / CPA

- systemd: `cliproxyapi.service`
- binary/config: `/root/cliproxyapi/cli-proxy-api`, `/root/cliproxyapi/config.yaml`
- auth material: `/root/.cli-proxy-api/` (private snapshot only)
- listener: all interfaces `8317`; remote management enabled; Usage Keeper integrations configured.
- Current observed config has `proxy-url: ""` (empty). This supersedes old notes that described a Taiwan proxy URL in CPA itself.
- Preserve `api-keys`, management secret, auth JSON and binary from the private archive; do not reconstruct these manually from chat.

### CPA Usage Keeper

- Docker container: `cpa-usage-keeper`; direct `8080:8080`; `restart=unless-stopped`
- Data volume: `/root/cpa-usage-keeper/data:/data`
- private env: `/root/cpa-usage-keeper/env.list`
- Saved image and live data are in the snapshot. Recreate after Docker starts; do not expose credentials in shell history/output.

### Cursor/image sidecars

| Unit | Loopback listener | Upstream | Drop-in behavior |
|---|---:|---:|---|
| `cursor-cpa-compat.service` | 8326 | `127.0.0.1:8317` | outbound `HTTP(S)/ALL_PROXY=http://127.0.0.1:7890`; loopback `NO_PROXY` |
| `subapi-cursor-compat.service` | 8327 | `127.0.0.1:3000` | same Mihomo drop-in |
| `subapi-image-compat.service` | 8328 | `127.0.0.1:3000` | same Mihomo drop-in |

Current source code signatures at capture:

```text
cursor-cpa-compat/server.py      92939941ea0df623f4ae9fc930a1295d4fe894e23fb93503badb3841e76b2dd9
subapi-cursor-compat/server.py   9894a5192abadbbbb03a154eccad8fea212203817a3e57217cc3a400d6772bf0
subapi-image-compat/server.py    a14e450e6af5e96448ffdb6f7f676573883a524c3694f98ae919055f30fba9bc
```

`CURSOR_EMIT_USAGE_PREROLL` / `CURSOR_EMIT_USAGE_CHUNK` were **not present** in the live `subapi-cursor-compat` process environment at capture, so its code defaults apply. If Cursor Context Usage behavior needs a specific scheme, make it explicit in a dedicated systemd drop-in and validate with a real Cursor session; do not infer it from an old screenshot.

### Mihomo and Xray

- Mihomo: `/etc/mihomo/config.yaml`, `mihomo.service`; loopback-only `7890` mixed, `7891` SOCKS, `9090` controller; `TW_HOME` group with `MATCH,TW_HOME` rule.
- Xray: `/usr/local/etc/xray/config.json`, `xray.service`; public `38443` VLESS + REALITY. Raw client ID / private key / short ID are snapshot-only.
- Start Mihomo before sidecars because all three sidecar units carry the local proxy drop-in.

### Data Collection Center / crawler

- Web service: `data-collection-center.service`, `/root/data-collection-center/app`, public `18084`.
- Env: `/root/data-collection-center/data-collection-center.env`; Basic Auth and database path are private snapshot data.
- Current app start: `node dist/web/server.js`; package lock is retained; reinstall with `npm ci` after restore.
- Scheduled collection: `dc-forum-collect.timer` every 15 minutes; local collector DB only (`DC_REMOTE_ENABLED=false`).
- Scheduled details: `dc-forum-detail-backfill.timer` every 20 minutes; it uses NodeSeek browser profile/cookies in the crawler tree.
- Crawler: `/root/nodeseek-crawler`, virtualenv rebuildable from `requirements.txt`; its working tree has uncommitted runtime changes. The archive, not the Git `HEAD` alone, is the migration source of truth.
- Do not re-enable any old Windows/VPS1 DC scheduler during a VPS2 migration.

### UI / static projects

| Unit | Directory | Listener / route |
|---|---|---|
| `subapi-image-demo.service` | `/opt/subapi-image-demo` | loopback `8798`; `https://image.aigcfast.com/` |
| `ai-ops-control-center.service` | `/root/ai-ops-control-center` | public `8799`; `/dashboard/` proxy |
| `aigcfast-static.service` | `/root/aigcfast-static` | public `3021`; prepared apex HTTP vhost |

Retain image demo `public/` assets and `.env` from the private archive; re-create `node_modules` from `package-lock.json`.

### Hermes

- Config/cron/scripts are snapshoted from `/root/.hermes/`.
- Config points at local New API (`http://127.0.0.1:3000/v1`) with provider `subapi`; default model `grok-composer-2.5-fast`.
- Service failed after Telegram network errors and has a Mihomo proxy drop-in. The environment notes intentionally avoid cloning a VPS bot token by default. Keep the unit disabled until ownership/bot conflict is intentionally resolved.

---

## 7. Recovery sequence

1. **Preflight new host:** Debian 12-compatible OS; root SSH key login; enough disk for the private archive plus restored data; Docker, nginx, certbot, Node/npm, Python, and systemd available.
2. **Transfer and verify archive SHA** before extracting.
3. **Extract to a staging directory**, then restore system files/paths only on an empty or explicitly approved target. Never overwrite a running unrelated New API/CPA stack without a DB/config backup.
4. **Load saved Docker images**, restore New API compose/data, then start `new-api`.
5. **Recreate CPA Usage Keeper** with its private env and data volume; then start CLIProxyAPI.
6. **Start Mihomo**, then CPA/Cursor/Image sidecars, TrafficLens, Xray, UI services, and Nginx. Run `nginx -t` first.
7. **Rebuild dependencies:** DC app `npm ci`; image demo `npm ci --omit=dev`; crawler virtualenv + `pip install -r requirements.txt`.
8. **Restore/start DC only after its SQLite integrity check succeeds**, then enable both timers. Avoid overlapping `flock` jobs.
9. **Keep Hermes disabled** until a deliberate separate decision.
10. **Validate locally and with `--resolve`**, then make the narrowly authorized DNS change(s).

---

## 8. Acceptance commands and expected shapes

```bash
# config / runtime
nginx -t
systemctl is-active nginx mihomo cliproxyapi cursor-cpa-compat \
  subapi-cursor-compat subapi-image-compat trafficlens-cpa-debug xray \
  data-collection-center subapi-image-demo ai-ops-control-center
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

# local no-auth shapes: 200 for status, JSON 401 for protected models
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/status
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8317/v1/models
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8326/v1/models
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8327/v1/models
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8328/v1/models

# forced-SNI tests before DNS cutover; replace NEW_IP
curl -k --resolve api.aigcfast.com:443:NEW_IP \
  -o /dev/null -w '%{http_code}\n' https://api.aigcfast.com/management.html
curl -k --resolve subapi.aigcfast.com:443:NEW_IP \
  -o /dev/null -w '%{http_code}\n' https://subapi.aigcfast.com/api/status
curl -k --resolve image.aigcfast.com:443:NEW_IP \
  -o /dev/null -w '%{http_code}\n' https://image.aigcfast.com/

# SQLite integrity after restore
python3 - <<'PY'
import sqlite3
for path in [
 '/root/new-api/data/one-api.db',
 '/root/data-collection-center/app/data/collector.db',
 '/root/cpa-usage-keeper/data/app.db',
]:
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    print(path, db.execute('pragma quick_check').fetchone()[0])
    db.close()
PY
```

Expected public no-auth shapes observed at capture: `api /management.html = 200`, `api /v1/models = 401 JSON`, `subapi /api/status = 200`, `subapi /v1/models = 401 JSON`, `subapi /cursor/v1/models = 401 JSON`, `image / = 200`, `image /v1/models = 401 JSON`.

---

## 9. Change-record requirement

After every migration or material routing change, update:

```text
/root/AGENTS.md
/root/VPS_OPERATIONS_LOG.md
/root/VPS2_MIGRATION_RUNBOOK.md
```

Record only: timestamp, target/source, files changed, backup/snapshot path, service/container actions, exact verification result, DNS status, rollback command, and unresolved risk. **Never record raw secrets.**
