---
name: linux-outbound-proxy-mihomo
description: "用于实现通用 Linux 服务器出站代理方案：使用本机 mihomo 拉取或转换订阅节点，提供 mixed/socks 代理端口，验证出口 IP 和地区，通过环境变量或软件自身代理配置接入应用，并配置 watchdog 故障切换和回退。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [linux, vps, outbound-proxy, mihomo, clash, proxy, systemd, watchdog, failover]
    related_skills: [vps-operations]
---

# Linux 出站代理实现流程：mihomo 本机代理 + 健康检测 + 回退

## 目标

本 skill 记录一套**通用 Linux 服务器出站代理方案**。

它不绑定任何具体业务软件。核心是：在 Linux 服务器上部署本机代理客户端，例如 `mihomo`，由它提供本机代理端口，然后让需要代理出站的软件显式接入这些本机端口。

标准形态：

```text
Linux VPS / Linux 服务器
  -> mihomo systemd 服务
  -> 本机 mixed / socks 代理端口
  -> 机场订阅或手动节点
  -> 指定代理组/节点
  -> 应用通过 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / app-level proxy 配置接入
  -> watchdog 检测代理出口
  -> 代理故障时切换节点或触发回退动作
```

核心原则：

1. 不默认改系统全局路由。
2. 不默认开启 TUN。
3. 先部署本机代理客户端。
4. 先验证代理出口可用。
5. 再让具体软件使用本机代理端口。
6. 需要健康检测和回退方案。
7. 代理不可用时，不能让依赖代理的服务一直卡死。

## 适用场景

当用户要求以下任务时，使用本 skill：

- Linux 服务器出站流量走代理。
- VPS 走机场节点。
- 服务器走台湾、香港、日本、美国等指定地区出口。
- 只让某个 Linux 服务走代理。
- 不改全局路由，只给指定程序配置代理。
- 代理挂了自动切换节点。
- 代理挂了自动回退。
- 在另一台 Linux 机器复刻出站代理方案。
- 检查服务器当前是否走代理。
- 检查本机 `mihomo` / `clash` 代理状态。
- 把订阅节点转换成服务器可用的本机代理服务。

不使用本 skill 处理：

- 具体业务软件安装。
- 反向代理入口流量。
- Cloudflare / DNS / HTTPS 证书。
- 浏览器指纹、账号池、桌面 GUI 代理客户端。
- Windows / macOS 客户端代理。

## 方案分层

### 1. 本机代理层

推荐使用：

```text
mihomo
```

也就是 Clash.Meta / MetaCubeX/mihomo。

它负责：

- 读取节点配置。
- 连接机场/代理节点。
- 提供本机代理端口。
- 提供本机 API 给 watchdog 查询和切换节点。
- 输出代理连接日志。

推荐监听：

```yaml
mixed-port: 7890
socks-port: 7891
external-controller: 127.0.0.1:9090
allow-lan: false
mode: rule
tun:
  enable: false
```

说明：

| 配置 | 含义 |
|---|---|
| `mixed-port: 7890` | HTTP + SOCKS 混合代理端口，最常用 |
| `socks-port: 7891` | SOCKS5 端口 |
| `external-controller: 127.0.0.1:9090` | 本机控制 API |
| `allow-lan: false` | 不对外开放代理端口 |
| `tun.enable: false` | 不劫持系统全局流量 |

### 2. 应用接入层

不同软件用不同方式接入本机代理。

#### 环境变量

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export ALL_PROXY=socks5://127.0.0.1:7891
export NO_PROXY=127.0.0.1,localhost,::1

export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
export all_proxy=socks5://127.0.0.1:7891
export no_proxy=127.0.0.1,localhost,::1
```

#### systemd 服务环境变量

给某个 systemd 服务加 override：

```bash
systemctl edit your-service
```

写入：

```ini
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7890"
Environment="HTTPS_PROXY=http://127.0.0.1:7890"
Environment="ALL_PROXY=socks5://127.0.0.1:7891"
Environment="NO_PROXY=127.0.0.1,localhost,::1"
```

应用：

```bash
systemctl daemon-reload
systemctl restart your-service
```

#### 单次命令代理

```bash
HTTPS_PROXY=http://127.0.0.1:7890 curl https://api.ipify.org
curl -x http://127.0.0.1:7890 https://api.ipify.org
```

#### 软件自带代理配置

如果某个软件支持 `proxy`、`proxy-url`、`http_proxy`、`https_proxy`、`outbound_proxy` 等配置，优先使用软件自己的配置项，指向：

```text
http://127.0.0.1:7890
```

这样影响范围最小，也方便回滚。

## 实现步骤

### 1. 安装 mihomo

确认系统架构：

```bash
uname -m
```

常见对应关系：

| 架构 | 下载包 |
|---|---|
| `x86_64` | linux-amd64 |
| `aarch64` | linux-arm64 |

推荐安装位置：

```bash
/usr/local/bin/mihomo
```

验证：

```bash
mihomo -v
```

### 2. 创建配置目录

```bash
mkdir -p /etc/mihomo
chmod 700 /etc/mihomo
```

推荐文件：

```text
/etc/mihomo/config.yaml
/etc/mihomo/config.yaml.subscription
/etc/mihomo/config.yaml.bak.<timestamp>
```

说明：

| 文件 | 用途 |
|---|---|
| `config.yaml` | 当前生效配置 |
| `config.yaml.subscription` | 拉取到的订阅原始文件或转换结果 |
| `config.yaml.bak.*` | 回滚备份 |

### 3. 拉取订阅但先不要启用

原则：**先拉取，先不要开，逐步测试。**

```bash
curl -fsSL '<SUBSCRIPTION_URL>' -o /etc/mihomo/config.yaml.subscription
chmod 600 /etc/mihomo/config.yaml.subscription
```

注意：

- 不要把订阅 URL 打印到聊天。
- 不要把 `uuid`、`password`、`token`、完整节点 URI 打印到日志或回复。
- 拉取后先解析和筛选，不要直接覆盖当前生效配置。

### 4. 解析订阅

订阅常见形态：

| 形态 | 特征 | 处理 |
|---|---|---|
| Clash YAML | 直接有 `proxies:` / `proxy-groups:` | 可裁剪后使用 |
| base64 URI 列表 | decode 后是 `vmess://`、`ss://`、`trojan://` | 需要转换为 mihomo YAML |
| provider 禁止 Clash 参数 | `?flag=clash` / `?target=clash` 返回 403 | 不要假设可导出 Clash |

base64 订阅检测：

```bash
python3 - <<'PY'
from pathlib import Path
import base64

p = Path('/etc/mihomo/config.yaml.subscription')
raw = p.read_bytes().strip()

try:
    decoded = base64.b64decode(raw + b'=' * (-len(raw) % 4), validate=False)
    text = decoded.decode('utf-8', 'ignore')
    for line in text.splitlines()[:10]:
        print(line[:120])
except Exception as e:
    print(type(e).__name__, e)
PY
```

过滤假节点。名称中包含以下内容的通常不是可用出口：

```text
流量
重置
套餐
到期
Telegram
公告
官网
订阅
V6
IPV6
```

### 5. 写入最小 mihomo 配置

示例：

```yaml
mixed-port: 7890
socks-port: 7891
external-controller: 127.0.0.1:9090
allow-lan: false
mode: rule
log-level: info
ipv6: false

tun:
  enable: false

proxies:
  - name: "node-1"
    type: vmess
    server: example.com
    port: 12345
    uuid: REDACTED
    alterId: 0
    cipher: auto
    network: ws
    ws-opts:
      path: /
      headers:
        Host: example-host

proxy-groups:
  - name: OUTBOUND
    type: select
    proxies:
      - "node-1"

rules:
  - MATCH,OUTBOUND
```

多个候选节点：

```yaml
proxy-groups:
  - name: OUTBOUND
    type: select
    proxies:
      - "node-1"
      - "node-2"
      - "node-3"
```

### 6. systemd 管理 mihomo

创建：

```text
/etc/systemd/system/mihomo.service
```

内容：

```ini
[Unit]
Description=mihomo proxy service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mihomo -f /etc/mihomo/config.yaml
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now mihomo
```

检查：

```bash
systemctl is-active mihomo
ss -ltnp | grep -E ':(7890|7891|9090)\b'
journalctl -u mihomo -n 30 --no-pager
```

### 7. 验证代理出口

必须验证直连和代理出口：

```bash
echo DIRECT=$(curl -sS --max-time 12 https://api.ipify.org || echo FAIL)
echo PROXY=$(curl -sS --max-time 25 -x http://127.0.0.1:7890 https://api.ipify.org || echo FAIL)
```

期望：

```text
DIRECT=<服务器原始 IP>
PROXY=<代理节点 IP>
```

如果目标是指定地区节点，继续查 IP 地区：

```bash
curl -sS --max-time 20 -x http://127.0.0.1:7890 https://ipapi.co/json/
```

同时看 mihomo 日志：

```bash
journalctl -u mihomo -n 50 --no-pager
```

期望看到：

```text
match Match using OUTBOUND[节点名]
```

只有代理出口验证成功，才让业务服务接入它。

## 应用接入代理

### 临时命令

```bash
curl -x http://127.0.0.1:7890 https://api.ipify.org
```

### 当前 shell

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export ALL_PROXY=socks5://127.0.0.1:7891
export NO_PROXY=127.0.0.1,localhost,::1

export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export all_proxy=$ALL_PROXY
export no_proxy=$NO_PROXY
```

验证：

```bash
curl https://api.ipify.org
```

### systemd 服务

```bash
systemctl edit your-service
```

写入：

```ini
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7890"
Environment="HTTPS_PROXY=http://127.0.0.1:7890"
Environment="ALL_PROXY=socks5://127.0.0.1:7891"
Environment="NO_PROXY=127.0.0.1,localhost,::1"
```

应用：

```bash
systemctl daemon-reload
systemctl restart your-service
```

检查服务环境：

```bash
systemctl show your-service -p Environment
```

### Docker 容器

如果容器需要代理，通常用环境变量：

```bash
docker run \
  -e HTTP_PROXY=http://host.docker.internal:7890 \
  -e HTTPS_PROXY=http://host.docker.internal:7890 \
  -e ALL_PROXY=socks5://host.docker.internal:7891 \
  -e NO_PROXY=127.0.0.1,localhost,::1 \
  ...
```

Linux Docker 默认不一定有 `host.docker.internal`，可加：

```bash
--add-host host.docker.internal:host-gateway
```

或者容器使用 host network：

```bash
--network host
```

则容器内可直接访问：

```text
127.0.0.1:7890
```

### 软件自带代理配置

如果软件支持自身代理配置，优先使用软件配置项指向：

```text
http://127.0.0.1:7890
```

优点：

- 影响范围小。
- 不改全局环境。
- 易于回滚。
- 不影响其他服务。

## watchdog：代理故障检测和回退

### 目标

watchdog 不绑定任何具体业务软件。它维护本机代理出口的健康状态：

```text
代理健康 -> 保持
代理失败 -> 计数
连续失败 -> 切换 mihomo 代理组节点
所有节点失败 -> 执行业务自定义回退动作
代理恢复 -> 执行业务自定义恢复动作
```

回退动作可以是：

- 只记录日志。
- 切换到另一个节点。
- 清除某个服务的代理环境变量。
- 改某个软件的代理配置为空。
- 重启依赖代理的服务。
- 切换 mihomo 到 `DIRECT` 规则。
- 触发通知或告警。

### 推荐 watchdog 配置

`/etc/linux-outbound-proxy-watchdog.env`：

```ini
MIXED_PORT=7890
MIXED_PROXY_URL=http://127.0.0.1:7890
MIHOMO_API=http://127.0.0.1:9090
MIHOMO_PROXY_GROUP=OUTBOUND

PROBE_URL=https://www.google.com/generate_204
PROBE_EXPECT_CODES=204

FAIL_THRESHOLD=2
RECOVER_THRESHOLD=2

STATE_DIR=/var/lib/linux-outbound-proxy-watchdog
LOG=/var/log/linux-outbound-proxy-watchdog.log

ON_PROXY_DEAD=
ON_PROXY_RECOVERED=
```

### watchdog 行为

```text
每分钟：

1. 检查 mihomo.service 是否 active。
2. 检查 127.0.0.1:7890 是否监听。
3. curl -x http://127.0.0.1:7890 探测外部 URL。
4. 成功：
   - fail_count 清零
   - mode=proxy
5. 失败：
   - fail_count +1
   - 未达阈值则不动
   - 达阈值后尝试切换代理组其他节点
   - 切换成功则恢复
   - 所有节点失败则执行 ON_PROXY_DEAD hook
6. 如果处于 fallback 状态：
   - 继续探测代理
   - 连续成功 RECOVER_THRESHOLD 次后执行 ON_PROXY_RECOVERED hook
```

### systemd timer

`/etc/systemd/system/linux-outbound-proxy-watchdog.service`：

```ini
[Unit]
Description=Linux outbound proxy watchdog (mihomo)
After=network-online.target mihomo.service
Wants=mihomo.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/linux-outbound-proxy-watchdog.sh
```

`/etc/systemd/system/linux-outbound-proxy-watchdog.timer`：

```ini
[Unit]
Description=Run Linux outbound proxy watchdog every minute

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now linux-outbound-proxy-watchdog.timer
```

## 检查当前是否走代理

### 直连 vs 代理 IP

```bash
echo DIRECT=$(curl -sS --max-time 12 https://api.ipify.org || echo FAIL)
echo PROXY=$(curl -sS --max-time 25 -x http://127.0.0.1:7890 https://api.ipify.org || echo FAIL)
```

判断：

| 结果 | 含义 |
|---|---|
| `DIRECT` 是服务器原始 IP | 直连出口 |
| `PROXY` 是代理节点 IP | 本机代理出口 |
| 两者不同 | 代理链路有效 |
| `PROXY=FAIL` | 本机代理不可用或节点不可用 |

### 查看服务是否配置代理

```bash
systemctl show your-service -p Environment
```

### 查看 mihomo 日志

```bash
journalctl -u mihomo -n 100 --no-pager
```

如果看到目标域名匹配到代理组：

```text
[TCP] 127.0.0.1:xxxxx --> target.domain:443 match Match using OUTBOUND[node-name]
```

说明该服务流量进入了本机代理。

## 回滚方式

### 停止某个服务使用代理

如果是 systemd 环境变量接入：

```bash
systemctl edit your-service
```

删除代理相关 `Environment=`，然后：

```bash
systemctl daemon-reload
systemctl restart your-service
```

如果是软件自带代理配置，将代理配置清空，然后按该软件方式重启。

### 停止 mihomo

```bash
systemctl disable --now mihomo
```

注意：如果服务仍然配置了 `HTTP_PROXY=http://127.0.0.1:7890`，停掉 mihomo 会导致该服务出站失败。应先移除服务代理配置。

## 常见坑

### 1. 以为配置了 mihomo 就是全系统走代理

不是。

默认不开 TUN 的情况下，只有显式使用以下地址的软件才会走代理：

```text
http://127.0.0.1:7890
socks5://127.0.0.1:7891
```

这是推荐做法，因为影响范围可控。

### 2. 没验证代理出口就让服务接入

必须先测：

```bash
curl -x http://127.0.0.1:7890 https://api.ipify.org
```

没通之前不要让业务服务使用它。

### 3. 代理组只有一个节点

这种情况下 watchdog 无法真正切节点，只能重启代理服务或执行回退 hook。

### 4. 把订阅里的元信息当节点

解析订阅时要过滤：

```text
流量
重置
套餐
到期
Telegram
公告
官网
订阅
V6
IPV6
```

这些一般不是可用出口。

### 5. Docker 容器里的 127.0.0.1 不是宿主机

容器内的 `127.0.0.1` 是容器自己。

访问宿主机代理可以用：

```bash
--network host
```

或：

```bash
--add-host host.docker.internal:host-gateway
```

然后使用：

```text
http://host.docker.internal:7890
```

### 6. 默认开启 TUN

TUN 会改变系统全局路由，风险更大。除非用户明确要求，否则不要默认使用 TUN。

### 7. 代理端口暴露公网

确保：

```yaml
allow-lan: false
external-controller: 127.0.0.1:9090
```

并检查防火墙和监听地址，不要把 `7890`、`7891`、`9090` 暴露给公网。

## 最终验收清单

- [ ] 明确这是通用 Linux 出站代理方案，不绑定具体业务软件。
- [ ] `mihomo` 已安装到 `/usr/local/bin/mihomo`。
- [ ] `/etc/mihomo/config.yaml` 存在。
- [ ] `tun.enable: false`。
- [ ] `allow-lan: false`。
- [ ] `mixed-port: 7890` 可用。
- [ ] `socks-port: 7891` 可用。
- [ ] `external-controller: 127.0.0.1:9090` 可用。
- [ ] `mihomo.service` active。
- [ ] `curl -x http://127.0.0.1:7890 https://api.ipify.org` 返回代理 IP。
- [ ] 直连 IP 和代理 IP 不同。
- [ ] 代理 IP 属于目标地区。
- [ ] 需要走代理的软件已通过环境变量、systemd override、Docker env 或软件自带代理配置接入。
- [ ] 不需要走代理的软件不受影响。
- [ ] watchdog timer enabled + active。
- [ ] watchdog 日志显示代理健康。
- [ ] 代理失败时能切换节点或触发回退 hook。
- [ ] 代理恢复后能触发恢复 hook。
- [ ] 代理端口未暴露公网。

## 实战案例 / 参考

- `references/vps2-tw-home-proxy-cpa-newapi.md` — VPS2 台湾家宽出站代理接入 CPA/New API/翻译层：订阅更新、台湾节点测速、`TW_HOME` 切换、CPA `proxy-url`、Docker New API 代理环境、`172.17.0.1` 必须加入 `NO_PROXY` 防止本机 CPA 请求误走代理导致 500。
