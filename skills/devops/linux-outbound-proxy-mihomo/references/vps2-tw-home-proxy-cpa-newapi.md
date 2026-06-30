# VPS2 台湾家宽出站代理接入：mihomo + CPA/New API

## 适用场景

Linux VPS 上已有 `mihomo` 本机代理，希望让 CPA / New API / 翻译层等服务出站走指定地区节点（例如台湾家宽），但不改变公网入口与系统全局路由。

本记录来自一次 VPS2 实操：`mihomo` 监听 `127.0.0.1:7890`，目标节点为 `🏠 [家宽] 1.0x 🇹🇼 台湾 TW - 2`。

## 关键原则

1. **先测试节点，再挂服务。** 不要看到 `127.0.0.1:7890` 监听就直接给业务服务加代理。
2. **不要开 TUN / 全局路由**，优先让服务显式使用 HTTP_PROXY 或软件自带 proxy 配置。
3. **Docker 容器访问宿主本地服务必须写入 NO_PROXY**，否则容器到宿主网桥的本地请求会被代理到外网，造成环回失败。
4. 改动前备份配置与数据库，尤其是 New API 容器重建前备份 `/root/new-api/data/one-api.db`。

## 测试流程

### 1. 确认 mihomo 入口与选择器

```bash
ss -tlnp | grep -E '127.0.0.1:(7890|7891|9090)'
curl -fsS http://127.0.0.1:9090/proxies/TW_HOME | jq .now
```

### 2. 更新订阅但先不要启用

```bash
stamp=$(date +%Y%m%d-%H%M%S)
cp -a /etc/mihomo/config.yaml.subscription /etc/mihomo/config.yaml.subscription.bak-$stamp 2>/dev/null || true
curl -fsSL '<SUBSCRIPTION_URL>' -o /etc/mihomo/config.yaml.subscription.new
mv /etc/mihomo/config.yaml.subscription.new /etc/mihomo/config.yaml.subscription
```

不要把订阅 URL、token、节点 URI 写入长期日志或文档。

### 3. 解析台湾节点并用临时 mihomo 测速

做法：把订阅中的目标节点解析成临时配置，启动临时实例，例如：

```bash
mkdir -p /tmp/mihomo-tw-test
# 写 /tmp/mihomo-tw-test/config.yaml
mihomo -d /tmp/mihomo-tw-test
```

临时端口建议：

```yaml
mixed-port: 17890
external-controller: 127.0.0.1:19090
allow-lan: false
mode: rule
```

然后对每个节点跑 controller delay：

```bash
curl 'http://127.0.0.1:19090/proxies/<URL_ENCODED_NODE>/delay?timeout=5000&url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204'
```

实操结果：订阅中台湾节点 17 个，更新后 4 个可用：

- `🎞️ 1.0x 🇹🇼 台湾 TW - 2`：约 129ms
- `🎞️ 1.0x 🇹🇼 台湾 TW - 4`：约 145ms
- `🏠 [家宽] 1.0x 🇹🇼 台湾 TW - 4`：约 189ms
- `🏠 [家宽] 1.0x 🇹🇼 台湾 TW - 2`：约 230ms

### 4. 真实 HTTPS 出站验证

必须验证 HTTPS，而不是只看 TCP 端口可连：

```bash
curl -fsS --max-time 25 --connect-timeout 8 \
  -x http://127.0.0.1:7890 \
  https://cloudflare.com/cdn-cgi/trace | grep -E '^(ip|colo|loc)='

curl -I --max-time 25 --connect-timeout 8 \
  -x http://127.0.0.1:7890 \
  https://api.openai.com/v1/models
```

期望：

- `loc=TW`
- `colo=TPE`
- OpenAI 未带 key 返回 `401`，表示链路正常。

## 服务接入

### CPA / CLIProxyAPI

优先用软件自带代理配置：

```yaml
# /root/cliproxyapi/config.yaml
proxy-url: "http://127.0.0.1:7890"
```

应用：

```bash
systemctl restart cliproxyapi
systemctl is-active cliproxyapi
```

验证：

```bash
python3 /root/.hermes/scripts/cpa_status_brief.py
journalctl -u mihomo -n 50 --no-pager | grep -E 'api.openai|auth.openai'
```

### New API / SubAPI Docker 容器

如果 New API 的上游 CPA 地址是宿主网桥，例如：

```text
http://172.17.0.1:8317
```

则容器代理环境必须包含：

```text
HTTP_PROXY=http://host.docker.internal:7890
HTTPS_PROXY=http://host.docker.internal:7890
ALL_PROXY=http://host.docker.internal:7890
NO_PROXY=127.0.0.1,localhost,host.docker.internal,new-api,172.17.0.1,172.17.0.0/16,10.0.0.0/8,192.168.0.0/16
```

**关键坑点：** 如果 `172.17.0.1` 不在 `NO_PROXY`，New API 请求本机 CPA 会被发到台湾代理，导致：

```text
HTTP 500
upstream error: do request failed
```

若主机没有 `docker compose` 插件，环境变量变更需要安全重建容器：

1. `docker inspect new-api` 保存镜像、端口、bind mounts、现有 env。
2. 备份 `/root/new-api/data/one-api.db`。
3. `docker stop new-api && docker rename new-api new-api-before-tw-proxy-<timestamp>`。
4. 用相同 image、bind、port、原 env + proxy env 重建。
5. 验证：

```bash
curl -fsS --max-time 8 http://127.0.0.1:3000/api/status
curl -fsS --max-time 30 http://127.0.0.1:3000/v1/chat/completions ...
```

未带 token 的 `401` 属于正常鉴权结果。

### systemd 翻译层 / 其他服务

为独立 Python/sidecar 服务添加 drop-in：

```ini
# /etc/systemd/system/<service>.service.d/10-tw-home-proxy.conf
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7890"
Environment="HTTPS_PROXY=http://127.0.0.1:7890"
Environment="ALL_PROXY=http://127.0.0.1:7890"
Environment="NO_PROXY=127.0.0.1,localhost,::1"
```

应用：

```bash
systemctl daemon-reload
systemctl restart cursor-cpa-compat subapi-cursor-compat subapi-image-compat
```

Hermes gateway 注意：从 Hermes Telegram 当前会话中直接 `systemctl restart hermes-gateway` 可能会被工具保护拦截，避免杀当前 gateway。需要用户发 `/restart` 或从外部 shell 操作。

## 回滚

CPA：

```bash
sed -i 's|^proxy-url:.*|proxy-url: ""|' /root/cliproxyapi/config.yaml
systemctl restart cliproxyapi
```

mihomo：

```bash
cp /etc/mihomo/config.yaml.bak-<timestamp> /etc/mihomo/config.yaml
mihomo -t -d /etc/mihomo
systemctl restart mihomo
```

New API：

```bash
docker rm -f new-api
docker rename new-api-before-tw-proxy-<timestamp> new-api
docker start new-api
```

systemd drop-ins：

```bash
rm -f /etc/systemd/system/<service>.service.d/10-tw-home-proxy.conf
systemctl daemon-reload
systemctl restart <service>
```

## 最终验收清单

- [ ] `curl -x http://127.0.0.1:7890 https://cloudflare.com/cdn-cgi/trace` 返回目标地区。
- [ ] `curl -x http://127.0.0.1:7890 https://api.openai.com/v1/models` 返回 401，而不是 TLS/timeout。
- [ ] `cliproxyapi` active，`proxy-url` 指向 `127.0.0.1:7890`。
- [ ] `new-api` active，容器 env 包含代理变量与 `172.17.0.1` NO_PROXY。
- [ ] New API → CPA 请求不再 500。
- [ ] sidecar 服务 active。
- [ ] VPS 运维账本 `/root/VPS_OPERATIONS_LOG.md` 记录变更、备份、回滚。
