# Hermes 技能库

这是用户私有的 Hermes Skill 仓库，用来统一保存、分类和版本管理常用技能。以后新增可复用流程、运维方案、开发规范、排障经验时，优先沉淀到这里，而不是散落在单独仓库或临时文件里。

## 仓库目标

- **统一归档**：所有用户自定义 skill 都放在本仓库 `skills/` 目录下。
- **按领域分类**：使用 Hermes 常见分类目录，例如 `devops`、`software-development`、`research`、`productivity`。
- **全中文维护**：README、说明、操作流程、注意事项默认使用中文。
- **可复用优先**：记录稳定流程和踩坑，不记录一次性任务进度。
- **可提交可回滚**：每次新增或修改 skill 都通过 git commit 管理。

## 目录结构

```text
skills/
  devops/
    cursor-subapi-compat/
      SKILL.md
      references/
    subapi-gpt-image2-compat/
      SKILL.md
      references/
      scripts/
    linux-outbound-proxy-mihomo/
      SKILL.md
  software-development/
    hermes-self-iteration/
      SKILL.md
      references/
        professional-iteration-report.md
```

## 当前技能索引

| 分类 | Skill | 用途 |
|---|---|---|
| `devops` | `cursor-subapi-compat` | Cursor IDE 接 SubAPI：Override Base `https://subapi.aigcfast.com/cursor/v1`、SubAPI sk、8327 兼容层与排障（回看用）。 |
| `devops` | `subapi-gpt-image2-compat` | SubAPI gpt-image-2：Nginx→8328 错协议转 Images；Responses 流式 `response.completed`；不拼接侧车文案，仅映射官方 `data[0]`。 |
| `devops` | `linux-outbound-proxy-mihomo` | 通用 Linux 出站代理方案：mihomo 本机代理、订阅/节点处理、应用接入、出口验证、watchdog 故障切换与回退。 |
| `software-development` | `hermes-self-iteration` | Hermes 自我驱动迭代流程：分析、规划、执行、验证、复盘，适合持续改进项目、服务、文档和工作流。 |

## 分类规则

新增 skill 时按以下规则放置：

| 分类 | 放什么 |
|---|---|
| `devops` | VPS、Linux、Docker、systemd、代理、监控、备份、部署、服务运维。 |
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
5. `## 实现步骤` 或 `## 工作流`
6. `## 常用命令`
7. `## 常见坑`
8. `## 验收清单`

## 内容原则

- 默认中文。
- 写真实可执行命令，不写空泛描述。
- 不写明文密钥、token、订阅 URL、密码。
- 不把一次性进度、临时任务、PR 号、commit 号写进 skill。
- 如果流程和某个具体项目无关，应写成通用方案。
- 如果流程只适合某个项目，要在 skill 里明确边界。
- 每个 skill 都要有验证步骤和回滚/安全注意事项。

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
git add skills/<分类>/<skill-name>/SKILL.md README.md
git commit -m 'feat: add <skill-name> skill'
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

## 当前版本

本仓库当前定位：**用户私有 Hermes 技能库**。

后续所有用户自定义技能默认都归档到本仓库，并按分类维护。