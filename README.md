# Hermes 私有技能库（hermes-self-iteration-skill）

这个仓库是用户私有的 **Hermes Agent Skill / Runbook 知识库**，用于沉淀可复用的运维、开发、排障、自动化与自我迭代方法。它不是业务项目仓库，也不是临时事故流水账；它的核心作用是让 Hermes 和未来接手的 AI Agent 在遇到相似问题时，能直接复用成熟流程、命令、判断标准和避坑经验。

## 这个仓库的所有作用

| 作用 | 说明 | 放什么 |
|---|---|---|
| **Hermes Skill 源仓库** | 统一保存用户自定义 Hermes skills，按分类管理，方便复制/同步到 Hermes 本地技能目录。 | `skills/<分类>/<skill-name>/SKILL.md` |
| **可复用运维 Runbook** | 记录 VPS、Nginx、systemd、CPA/SubAPI、Cursor、TrafficLens 等可复用排障流程。 | `references/*.md`、`scripts/*`、验证命令 |
| **协议兼容方案档案** | 保存已经验证过的兼容层设计，例如 Cursor `/cursor/v1`、SubAPI gpt-image-2、Linux 出站代理等。 | 链路图、关键文件、转换规则、回滚方案 |
| **问题分析方法库** | 记录如何分析问题，而不是只记录“改了什么”。重点是证据链、分层判断、错误假设、最终根因。 | 排障路径、判断表、日志解读、最小验证命令 |
| **可复制脚本/模板仓库** | 存放可直接部署或改造的脚本、systemd unit、Nginx snippet、验证脚本。 | `scripts/`、`templates/` |
| **长期经验沉淀** | 保存稳定、可复用、未来还会用到的经验，避免下次重新踩坑。 | 常见坑、边界条件、验收清单 |
| **Git 版本化知识记录** | 所有重要技能/方案变化通过 commit 管理，可追溯、可回滚、可对比。 | commit history、文档 diff |

## 不是什么

| 不是 | 原因 | 应放哪里 |
|---|---|---|
| **不是业务源码仓库** | 不承载具体产品/服务的完整业务代码。 | 对应项目仓库，如 `ai-ops-control-center`、`data-collection-center` 等 |
| **不是现网事故流水账** | 临时时间线、一次性命令输出、当次状态容易过期。 | VPS `/root/VPS_OPERATIONS_LOG.md`、专门 ops/incident 仓库 |
| **不是密钥/配置备份库** | 不能存 token、密码、cookie、订阅 URL、私钥、完整环境变量。 | 受控 secret store、本机/VPS 安全配置文件 |
| **不是聊天记录归档** | 会话进度、PR 号、临时 TODO 一周内就会过期。 | Hermes session history 或任务系统 |
| **不是每次修复的完整审计库** | 只保留可复用结论，不堆全部原始日志。 | 事故复盘文档或机器本地日志 |

## 内容边界：Skill vs Reference vs Incident

### 1. `SKILL.md`：技能入口，写“什么时候用 + 怎么做”

`SKILL.md` 应保持短而准，适合 Hermes 在任务开始前加载：

- 适用场景 / 不适用场景
- 最短工作流
- 核心命令
- 常见坑
- 验证步骤
- 指向更详细 `references/*.md`

不要把大量事故时间线、原始日志、一次性调试输出塞进 `SKILL.md`。

### 2. `references/*.md`：可复用详细方案 / 排障记录

`references/` 可以放更长的文档，但仍要满足“未来可复用”：

- 复杂问题的分层分析方法
- 已验证的修复方案
- 协议/链路设计说明
- 典型日志形态与解读方式
- 回滚与验收命令
- 必要的事故复盘，但要提炼成通用判断标准

如果文档里包含具体时间线，应说明哪些是“本次证据”，哪些是“长期方法”。

### 3. `scripts/`：可复制执行物

适合放：

- 兼容层服务脚本
- systemd unit
- Nginx snippet
- 部署/验证脚本
- 只读诊断脚本

脚本必须避免内置秘密；如需密钥，应从环境变量或安全配置读取。

### 4. 现网事故流水：只在必要时提炼后进入本仓库

完整事故过程更适合放在：

```text
/root/VPS_OPERATIONS_LOG.md
/root/AGENTS.md
专门 ops/incident 仓库
```

本仓库只保留其中能复用的部分：根因、错误假设、判断命令、最终方案、回滚方式。

## 当前目录结构

```text
skills/
  devops/
    cursor-subapi-compat/
      SKILL.md
      references/
      scripts/
    subapi-gpt-image2-compat/
      SKILL.md
      references/
      scripts/
    linux-outbound-proxy-mihomo/
      SKILL.md
      references/
  software-development/
    hermes-self-iteration/
      SKILL.md
      references/
```

## 当前技能索引

| 分类 | Skill | 作用 |
|---|---|---|
| `devops` | `cursor-subapi-compat` | Cursor IDE 接 `api.aigcfast.com` / `subapi.aigcfast.com` 的 `/cursor/v1` 兼容层、CPA/SubAPI 路由、call_id、Responses↔ChatCompletions 工具桥接与排障。 |
| `devops` | `new-api-admin-ops` | New API/SubAPI 面板、计费、模型、令牌、日志与 nginx/API 路由排障；包含 `/v1/responses` 413 active-DNS-host 修复记录。 |
| `devops` | `subapi-gpt-image2-compat` | SubAPI `gpt-image-2` 文生图/图生图兼容：Nginx→8328、Images API 映射、官方 JSON 返回、非聊天路径边界。 |
| `devops` | `linux-outbound-proxy-mihomo` | 通用 Linux 出站代理方案：mihomo 本机代理、订阅/节点处理、应用接入、出口验证、watchdog 与回退。 |
| `software-development` | `hermes-self-iteration` | Hermes 自我驱动迭代流程：分析、规划、执行、验证、复盘，适合持续改进服务、文档和工作流。 |

## 分类规则

| 分类 | 放什么 |
|---|---|
| `devops` | VPS、Linux、Docker、systemd、Nginx/OpenResty、CPA/SubAPI、代理、监控、备份、部署、服务运维。 |
| `software-development` | 编码流程、调试方法、测试规范、项目迭代、代码审查、工程实践。 |
| `research` | 信息检索、资料分析、论文/博客/情报监控。 |
| `productivity` | 文档、表格、办公自动化、汇报模板。 |
| `media` | 图片、音频、视频、可视化处理。 |

不要轻易新增顶层分类；能归入现有分类就使用现有分类。

## Skill 编写规范

每个 skill 使用如下结构：

```text
skills/<分类>/<skill-name>/SKILL.md
```

`SKILL.md` 必须包含 YAML frontmatter：

```yaml
---
name: skill-name
description: "中文说明：什么时候使用这个 skill，以及它解决什么问题。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [tag1, tag2]
    related_skills: []
---
```

正文建议包含：

1. `# 标题`
2. `## 目标`
3. `## 适用场景`
4. `## 不适用场景`
5. `## 工作流 / 实现步骤`
6. `## 常用命令`
7. `## 常见坑`
8. `## 验收清单`
9. `## 回滚 / 安全边界`

## 内容原则

- 默认中文。
- 写真实可执行命令，不写空泛描述。
- 不写明文密钥、token、订阅 URL、密码、cookie。
- 不把一次性进度、临时任务、PR 号、commit 号写进 skill 主体。
- 如果流程和具体项目无关，应写成通用方案。
- 如果流程只适合某个项目，要明确边界。
- 每个 skill 都要有验证步骤和回滚/安全注意事项。
- 复杂事故要提炼成“可复用分析方法”，不要只贴日志。
- 对生产服务的变更记录，要同步写到对应 VPS/项目的 AGENTS/OPERATIONS_LOG，而不是只写本仓库。

## 安装到 Hermes

从仓库复制某个 skill 到 Hermes 用户技能目录，例如：

```bash
mkdir -p ~/.hermes/skills/devops/linux-outbound-proxy-mihomo
cp skills/devops/linux-outbound-proxy-mihomo/SKILL.md \
  ~/.hermes/skills/devops/linux-outbound-proxy-mihomo/SKILL.md
```

也可以复制整个 `skills/` 目录到 Hermes 用户技能目录。

## 维护流程

新增或修改 skill 后：

```bash
git status --short
git add skills/<分类>/<skill-name>/SKILL.md \
        skills/<分类>/<skill-name>/references/<doc>.md \
        README.md
git commit -m 'docs: update <skill-name> runbook'
git push origin main
```

提交前检查：

- [ ] frontmatter 可被 YAML 解析。
- [ ] `name` 和目录名一致。
- [ ] `description` 是中文，且不超过 1024 字符。
- [ ] 正文不是空模板，有实际流程。
- [ ] 没有泄露密钥、订阅 URL、token、cookie。
- [ ] 适用场景和不适用场景写清楚。
- [ ] 包含验证步骤。
- [ ] 包含常见坑或回滚方式。
- [ ] 如果是事故复盘，已经提炼成可复用方法，并说明哪些内容会过期。
- [ ] 未把无关临时文件、`.hermes-tmp*`、本地缓存加入 commit。

## 当前定位

本仓库当前定位：**用户私有 Hermes 技能库 + 可复用 Runbook 知识库**。

后续所有用户自定义技能、稳定流程、通用排障方案默认归档到本仓库；现网临时状态、完整事故流水、服务部署账本应放到对应 VPS/项目的运维记录中，再把可复用结论提炼回本仓库。
