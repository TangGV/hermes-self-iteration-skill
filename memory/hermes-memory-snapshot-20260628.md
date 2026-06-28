# Hermes 当前记忆快照（2026-06-28）

> 用途：按用户要求，把当前 Hermes 注入上下文里的持久记忆与用户偏好快照提交到私有技能/Runbook 仓库，便于审计、迁移和恢复。
>
> 注意：本文件包含 VPS、服务路径、Bot 标识、工作流偏好等运维上下文，默认只放在私有仓库。不要公开转载。未包含明文 token、密码、cookie、私钥内容。

## MEMORY（个人 notes / 环境事实）

- VPS SSH keys: `root@45.143.233.108` and `root@62.106.70.67` both use local key `C:\Users\t\.ssh\id_ed25519`; host keys are known.
- Windows Hermes default profile: config `C:\Users\t\AppData\Local\hermes\config.yaml` (not `C:\Users\t\.hermes`); Telegram `@SuxiHermesBot` uid `6252510490`; Feishu app `cli_aabb822e86631cc0` bot `小助理小马仔` WebSocket.
- On the user's Windows Hermes default profile, Hermes provider/model switching should stay CC Switch–first. CC Switch GUI is `D:\CC Switch\cc-switch.exe`; guard script `C:\Users\t\AppData\Local\hermes\scripts\ccswitch_hermes_guard.py` dedupes top-level custom_providers after CC Switch writes `config.yaml`; watchdog scripts live under `C:\Users\t\AppData\Local\hermes\scripts\ccswitch_watchdog_*.cmd`.
- AI Ops `C:\Users\t\ai-ops-control-center`→`TangGV/ai-ops-control-center`; public `:8799` no `?v`. App Operator `C:\Users\t\ai-app-operator`→private `TangGV/ai-app-operator`; MCP `app-operator`; use `.venv/Scripts/python.exe`; docs `DEPLOYMENT/USAGE/AGENTS`.
- DC 仅 VPS2 `collector.db`；用户「找 XX 的」要 SSH 查库、帖单+直链+简短结论，优先退款/封号/支付渠道；单数字=点选上条编号展开。`web-next` `fnm24+out2`→VPS2；检索验收见 `docs/dc-search-perf-2026-06-22.md`。
- 主项目 `C:\D`；CL=`crawler/nodeseek-crawler` 爬虫项目，`D:\nodeseek-crawler`→`TangGV/nodeseek-crawler`；反爬改完 `py_compile` 再 push。
- 私有技能库 `TangGV/hermes-self-iteration-skill`；分类 `skills/<cat>/<name>/`，中文 `README/SKILL`，改完 push。
- VPS1 `45.143.233.108`：SubAPI `subapi.aigcfast.com/v1`；`cursor/v1`→8326 CPA（journal `req/resp-audit` 看多轮 tool）。远程 TL MITM `:18888`，JSONL `/var/log/trafficlens/remote-cursor-mitm.jsonl`；官方 Agent 经 TL 多为 `api2.cursor.sh` proto。`cpa_status_*.py`。
- VPS2 `62.106.70.67`: Hermes `/usr/local/bin/hermes` `/root/.hermes`; bot `@linux_suxi2_bot`; gateway active; provider subapi model `grok-composer-2.5-fast`.
- VPS1 CPA：容器 `cpa-usage-keeper`，时区 `Asia/Shanghai`；状态用 `/root/scripts/cpa/cpa_status_brief.py`（非 `~/.hermes`）。
- SubAPI 生图：Base `/v1`；文生图 `/images/generations`；参考图/图生图 `/images/edits`，单图 `image`、多图 `image[]`；返回官方 JSON，取 `data[0].b64_json/url`。
- Cursor：直连 `/v1` 会 `call_id>64`；http Override 易无效 key；用 `https` + `/cursor/v1` + CPA 别名。

## USER PROFILE（用户偏好 / 工作方式）

- Telegram 主界面；Hermes/运维默认中文；默认极简短答，要详细再展开。每次回复写明模型/Provider。
- 采集数据、采集结果、健康报告不要主动 Telegram 通知，仅在用户要求时汇报。
- CL/DC/爬虫：用户明确要求才改代码。DC/web-next 改完须 build、部署 VPS2、push；默认外网验收 `https://api.aigcfast.com/datacenter/`，及时发布。
- 用户偏好直接执行已授权任务，少解释少反问；说“继续/全面干/一次性搞定/给我记住我让你干嘛你就干嘛”表示自主推进，做到可运行、已验证、必要时提交 git。
- PC/VPS/Cursor/CPA 运维要严谨：先分析链路，保护 token/服务/数据，真实日志/命令验证；Cursor/CPA 优先比较 direct `/v1`、`/cursor/v1`、代理路径与 TrafficLens/SSE/usage_events 证据；不接受 loop guard/止血作最终方案，必须追协议层 root cause。通用 Linux 出站代理方案/skill 要与具体软件解耦，不要写成 CPA 专用。
- VPS Hermes 的“CPA状态/统计/额度”必须跑实时 CPA probe 后再答，至少包含服务健康、tokens、key、reasoning/tier、额度窗口。不要从静态记忆猜。
- 用户熟悉并授权直接 VPS/server admin via SSH；自托管 Basic Auth 可使用用户指定的标准密码，但不要把明文秘密长期写入 memory/日志。
- Web/UI/CMS 工作偏好成熟前端+后台框架/模板/组件、官方预览、简洁更新；不要称正式交付为 demo；移动端优先适配。接口工具页面把 API 地址与 Key 放顶部首两行且不暗示默认值；声明“可访问”前验证前后端。
- 用户说“停止自我迭代/停止迭代/怎么停不下来”时，意图是停止所有相关自我迭代自动化：暂停/移除匹配 cron、杀后台进程和残留监听端口，而不只是停止当前回复。
- 讨论爬虫、反爬、采集实现时，只答工程与协议层（状态机、指纹一致性、adapter、限速、merge），不要把缺口率、面板预览、商业叙事当主结论；用户会纠正「跟技术没关系」。商业指纹浏览器类问题要按 ROI 讲（本机养号 vs VPS 无头、RSS/API 绕浏览器），不要当默认主方案。
- DC Next `/datacenter`：首页信息密度高、数据来自 `/api/workbench` 真实字段；入库检索默认 `last_seen→first_seen`；不恢复旧 Action Room 全屏壳。
- Cursor/CPA：TrafficLens 优先（VPS1 `:18888`、`G:\Downloads\trafficlens-windows-amd64` + launcher 只代理 Cursor、远程 TL 不限 IP）；`/cursor/v1`→8326；未走 launcher 则 TL 无 aigcfast。勿擅自 restart CPA/new-api。
- 用户偏好：写好的项目文档默认提交并 push 到对应 GitHub 仓库，除非明确说不提交。

## 上传说明

- 本快照来源于当前会话系统注入的持久 MEMORY 与 USER PROFILE。
- 快照适合用于迁移/审计，不代表应该长期作为唯一事实源；后续仍以 Hermes 实际 memory/user profile 为准。
- 如公开仓库或共享给第三方，应先脱敏 VPS IP、Bot 标识、路径、仓库名与运维细节。
