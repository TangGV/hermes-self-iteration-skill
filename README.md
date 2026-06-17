# Hermes Self-Iteration Skill / Hermes 自我驱动迭代技能

[中文](#中文说明) | [English](#english)

---

## 中文说明

**Hermes Self-Iteration Skill** 是一个面向 Hermes Agent 的上层执行协议。它的目标是让 AI 在用户给出目标对象和期望结果后，自动完成：

> **全面分析 → 找出问题/机会 → 制定迭代路线 → 自动执行改造 → 真实验证 → 继续下一轮 → 直到结果成熟或遇到硬阻塞。**

这个 skill 的重点不是“回答问题”，而是让 Agent 对一个项目、系统、服务、文档、工作流或产品想法进行 **自我驱动的连续升级**。

### 适合什么场景？

- 对一个代码仓库做自动架构分析、修复、测试补齐、重构和优化
- 对 VPS / 服务栈做健康分析、配置整理、监控与恢复流程强化
- 对爬虫 / 数据链路做可靠性、调度、验证闭环优化
- 对 Hermes 自身的配置、skills、memory、cron、网关流程做持续完善
- 对文档、方案、产品想法进行多轮打磨，直到达到可交付状态

### 核心理念

1. **自动，不等口令**  
   用户只需要给对象和方向，Agent 不应每一步都问“要不要继续”。

2. **先全面分析，再动手改造**  
   第一轮必须理解结构、依赖、运行方式、风险、质量和机会，而不是看到一个点就改一个点。

3. **验证是硬门槛**  
   没有测试、命令、日志、读回、健康检查等证据，不算完成。

4. **多轮升级，不一轮即停**  
   每轮后自动判断是否还有 P0/P1/P2 或高 ROI 改造点，必要时继续下一轮。

5. **沉淀能力**  
   可复用的流程和踩坑写入 skill；长期偏好和稳定事实写入 memory；单次进度不写 memory。

### AUTO-MATURE 闭环

```text
A. Analyze    全面分析现状、目标、约束、风险、机会
U. Understand 建立对象地图：结构、依赖、数据流、运行方式、历史决策
T. Target     定义成熟标准：什么叫“完善/成熟/可交付”
O. Optimize   自动选择最高价值改造点并执行

M. Measure    真实验证：测试、日志、健康检查、人工可读审查
A. Adapt      根据验证结果调整下一轮策略
T. Trace      记录决策、变更、证据、剩余问题
U. Upgrade    继续下一轮升级，不因完成一个小任务就停
R. Reflect    把可复用流程写回 skill/memory/项目文档
E. End        仅在成熟标准达成或硬阻塞时结束
```

### 安装

把 `SKILL.md` 放到 Hermes 用户技能目录：

```bash
mkdir -p ~/.hermes/skills/software-development/hermes-self-iteration
cp skills/software-development/hermes-self-iteration/SKILL.md   ~/.hermes/skills/software-development/hermes-self-iteration/SKILL.md
```

可选：为了防止 curator 自动归档该技能，可以 pin：

```bash
hermes curator pin hermes-self-iteration
```

### 使用示例

```text
用自我迭代优化这个项目。
```

```text
把这个服务自动分析并完善，直到成熟。
```

```text
用 hermes-self-iteration 迭代 hermes-self-iteration 自己。
```

### 重要边界

- 用户明确说“只分析 / 只计划 / 不改”时，不应进入改造。
- 生产、高风险、破坏性、凭证相关操作必须遵守安全边界。
- 任务进度不要写入 memory；只把长期偏好、稳定事实、可复用流程写入持久层。

---

## English

**Hermes Self-Iteration Skill** is a high-level execution protocol for Hermes Agent. Given a target object and a desired outcome, it instructs the agent to automatically perform:

> **Comprehensive analysis → identify issues/opportunities → define an iteration roadmap → execute improvements → verify with evidence → continue upgrading → stop only when mature or hard-blocked.**

This skill is not about answering a single question. It is about making the agent continuously improve a project, system, service, document, workflow, or product idea until it reaches a mature deliverable state.

### Use Cases

- Automatically analyze, fix, test, refactor, and optimize a code repository
- Inspect and harden a VPS or service stack with health checks and recovery workflows
- Improve crawler/data pipelines for reliability, scheduling, deduplication, and validation
- Continuously refine Hermes configuration, skills, memory, cron jobs, and gateway workflows
- Iterate on documents, plans, or product ideas until they become deliverable

### Core Principles

1. **Autonomous by default**  
   The user provides the target and direction; the agent should not ask for permission at every step.

2. **Analyze comprehensively before changing things**  
   The first round must understand structure, dependencies, runtime, risks, quality, and opportunities.

3. **Verification is mandatory**  
   A task is not complete without evidence: tests, command output, logs, read-back checks, health probes, or reviewable artifacts.

4. **Keep iterating, do not stop after one small fix**  
   After each round, the agent should decide whether remaining P0/P1/P2 issues or high-ROI improvements justify another round.

5. **Compound learning**  
   Reusable workflows and pitfalls go into skills; durable preferences and facts go into memory; one-off task progress does not.

### AUTO-MATURE Loop

```text
A. Analyze    Analyze current state, goals, constraints, risks, opportunities
U. Understand Map structure, dependencies, data flow, runtime, history
T. Target     Define maturity criteria: what “done/mature/deliverable” means
O. Optimize   Select and execute the highest-value improvement

M. Measure    Verify with tests, logs, health checks, or reviewable artifacts
A. Adapt      Adjust the next iteration based on verification results
T. Trace      Record decisions, changes, evidence, and remaining issues
U. Upgrade    Continue upgrading; do not stop after one small task
R. Reflect    Write reusable lessons into skills/memory/project docs
E. End        Stop only when maturity is reached or a hard blocker appears
```

### Installation

Copy `SKILL.md` into your Hermes user skill directory:

```bash
mkdir -p ~/.hermes/skills/software-development/hermes-self-iteration
cp skills/software-development/hermes-self-iteration/SKILL.md   ~/.hermes/skills/software-development/hermes-self-iteration/SKILL.md
```

Optional: pin it so the curator never archives it automatically:

```bash
hermes curator pin hermes-self-iteration
```

### Example Prompts

```text
Use self-iteration to improve this project.
```

```text
Analyze and upgrade this service automatically until it is mature.
```

```text
Use hermes-self-iteration to iterate hermes-self-iteration itself.
```

### Safety Boundaries

- If the user explicitly says “analysis only”, “plan only”, or “do not modify files”, do not execute changes.
- Production, destructive, credential-related, or high-risk operations must respect safety boundaries.
- Do not store one-off task progress in memory; only store durable preferences, stable facts, and reusable procedures.

---

## Repository Layout

```text
skills/software-development/hermes-self-iteration/SKILL.md
README.md
LICENSE
```

## License

MIT
