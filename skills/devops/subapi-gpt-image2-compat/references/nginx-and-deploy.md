# Nginx 与部署（SubAPI image-compat）

## OpenResty 片段（`subapi.aigcfast.com.conf`）

放在 `location /` 代理 New API **之前**：

```nginx
    location ^~ /subapi-image-artifacts/ {
        proxy_pass http://127.0.0.1:8328;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
        add_header Cache-Control "public, max-age=86400" always;
    }

    location = /v1/responses {
        proxy_pass http://127.0.0.1:8328;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        add_header X-SubAPI-Image-Route "image-compat" always;
    }
    location = /v1/chat/completions {
        proxy_pass http://127.0.0.1:8328;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        add_header X-SubAPI-Image-Route "image-compat" always;
    }
```

**注意：** 仅 **精确匹配** 上述两个路径；`/v1/images/generations` 仍走默认 `location /` → `:3000`。

## systemd

```ini
[Unit]
Description=SubAPI gpt-image-2 compat (responses/chat -> images/generations)
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=/root/subapi-image-compat
ExecStart=/usr/bin/python3 /root/subapi-image-compat/server.py
Restart=always
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now subapi-image-compat
```

## 部署流程（从本机脚本目录）

```bash
# 本机
bash C:/Users/t/AppData/Local/hermes/scripts/subapi-image-compat/deploy.sh
# 或 scp server.py + restart + 手工 patch nginx
scp server.py root@45.143.233.108:/root/subapi-image-compat/
ssh root@45.143.233.108 systemctl restart subapi-image-compat
```

部署前备份 vhost：`cp subapi.aigcfast.com.conf subapi.aigcfast.com.conf.bak-image-compat`

## 验证命令

```bash
# 流式是否含 completed
curl -sS -N -X POST 'https://subapi.aigcfast.com/v1/responses' \
  -H 'Authorization: Bearer sk-...' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"model":"gpt-image-2","input":"dot","stream":true}' | grep -E 'response.completed|\[DONE\]'

# 响应头
curl -sS -D - -o /dev/null -X POST 'https://subapi.aigcfast.com/v1/responses' \
  -H 'Authorization: Bearer sk-...' -H 'Content-Type: application/json' \
  -d '{"model":"gpt-image-2","input":"dot","stream":false}' | grep -i X-SubAPI-Image
```