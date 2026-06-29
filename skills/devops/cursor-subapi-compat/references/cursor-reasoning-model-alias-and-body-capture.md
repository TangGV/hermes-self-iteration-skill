# Cursor `/cursor/v1` reasoning/model alias/body-capture analysis

## 结论

Cursor 自定义 OpenAI Base 走 `https://subapi.aigcfast.com/cursor/v1` 时，当前观测到的真实 ChatCompletions 入参**不会显式携带** `reasoning` / `reasoning_effort` / `metadata` / `extra_body` / `max_mode` / `context_window` 等字段。

全量请求体捕获显示顶层字段只有：

```text
messages
model
stream
stream_options
tools
user
```

其中：

```text
model = gpt-5.5 或 gpt-5.5-extra
stream_options.include_usage = true
```

`MAX Mode`、`Context 1M`、`Reasoning Medium/High/Extra High` 这些 Cursor UI 选项没有作为独立 JSON 字段进入自定义 Base 请求；Context/记忆主要体现为 Cursor 塞进 `messages` 的内容与长度。

## 与 Codex `/v1` 的差异

Codex CLI 使用 `https://subapi.aigcfast.com/v1` 时会直接走 Responses API，并显式发送/触发标准推理字段；New API/SubAPI 后台日志能看到：

```text
request_path=/v1/responses
reasoning_effort=low|medium|high
```

所以“Codex low 推理可用”不能反推 Cursor `/cursor/v1` 也会显式传 `reasoning_effort`。两条链路不同：

```text
Codex CLI → /v1 → /v1/responses → reasoning_effort 显式字段
Cursor → /cursor/v1 → ChatCompletions 兼容请求 → 翻译服务补 Responses 字段
```

## 当前映射规则

因为 Cursor 对自定义 Base 当前只稳定传模型名，翻译层用模型名补推理难度：

| Cursor 发来 | 转发给上游 |
|---|---|
| `gpt-5.5` | `model=gpt-5.5` + `reasoning.effort=high` |
| `gpt-5.5-extra` | `model=gpt-5.5` + `reasoning.effort=xhigh` |

显式 `reasoning` / `reasoning_effort` 一旦存在，必须原样保留，不用模型别名覆盖。

## 全量捕获方法

用户要求“全量分析 Cursor 过来的字段内容”时，可临时开启 SubAPI Cursor 翻译服务的完整 body 捕获：

```text
CURSOR_FULL_CAPTURE=1
CURSOR_CAPTURE_DIR=/var/log/cursor-full-capture
```

捕获文件：

```text
/var/log/cursor-full-capture/subapi-latest.json
```

注意：

- 不记录 HTTP Authorization / Key。
- 默认最大 2MB，超限时只保留最后 20 条 messages。
- 完成分析后必须关闭，除非用户明确要求继续打开。
- Telegram 汇报不要粘贴完整 messages，只汇总字段和必要片段。

## 关闭捕获

默认应为关闭：

```python
CURSOR_FULL_CAPTURE = os.getenv("CURSOR_FULL_CAPTURE", "0").lower() in {"1", "true", "yes", "on"}
```

## 审计证据

全量捕获中的典型字段：

```text
top_keys = [messages, model, stream, stream_options, tools, user]
model = gpt-5.5
stream_options = {"include_usage": true}
metadata = missing
extra_body = missing
reasoning = missing
reasoning_effort = missing
```

翻译后服务日志应显示：

```text
model=gpt-5.5 reasoning='high'
model=gpt-5.5 reasoning='xhigh'   # 当 Cursor 发 gpt-5.5-extra
```
