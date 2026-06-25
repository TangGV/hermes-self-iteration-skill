#!/usr/bin/env bash
# Deploy subapi-image-compat to VPS1 and patch OpenResty vhost.
set -euo pipefail
HOST=root@45.143.233.108
KEY="${HOME}/.ssh/id_ed25519"
SRC="$(cd "$(dirname "$0")" && pwd)"
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'mkdir -p /root/subapi-image-compat'
scp -i "$KEY" -o BatchMode=yes "$SRC/server.py" "$SRC/subapi-image-compat.service" "$HOST:/root/subapi-image-compat/"
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'cp /root/subapi-image-compat/subapi-image-compat.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now subapi-image-compat.service'
CONF=/opt/1panel/www/conf.d/subapi.aigcfast.com.conf
ssh -i "$KEY" -o BatchMode=yes "$HOST" "test -f $CONF.bak-image-compat || cp $CONF $CONF.bak-image-compat"
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'python3 <<'"'"'PY'"'"'
from pathlib import Path
p = Path("/opt/1panel/www/conf.d/subapi.aigcfast.com.conf")
t = p.read_text()
marker = "    # gpt-image-2 compat"
if marker in t:
    print("nginx already patched")
    raise SystemExit(0)
block = """
    # gpt-image-2 compat: responses/chat with gpt-image-* -> 8328 (else passthrough to New API)
    location = /v1/responses {
        proxy_pass http://127.0.0.1:8328;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_connect_timeout 60s;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        add_header X-SubAPI-Image-Route image-compat always;
    }
    location = /v1/chat/completions {
        proxy_pass http://127.0.0.1:8328;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_connect_timeout 60s;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        add_header X-SubAPI-Image-Route image-compat always;
    }

"""
needle = "    location / {"
if needle not in t:
    raise SystemExit("needle not found")
t = t.replace(needle, block + needle, 1)
p.write_text(t)
print("nginx patched")
PY'
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'docker exec 1Panel-openresty-HMuJ openresty -t 2>/dev/null || docker ps --format "{{.Names}}" | grep -i openresty | head -1 | xargs -I{} docker exec {} openresty -t'
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'docker ps --format "{{.Names}}" | grep -i openresty | head -1 | xargs -I{} docker exec {} openresty -s reload'
echo deploy done