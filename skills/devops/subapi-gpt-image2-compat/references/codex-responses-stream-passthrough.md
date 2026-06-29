# SubAPI `/v1` Responses 流式透传修复记录

## 现象

Codex++ 供应商配置为：

```text
Base URL: https://subapi.aigcfast.com/v1
上游协议: Responses API
```

但用户看到：

- 回复像一次性返回，没有打字机效果；
- “思考时间”显示 0 或异常；
- 后台日志仍能看到 `/v1/responses`、`is_stream=true`，说明请求协议本身不是完全走错。

## 链路

当前 SubAPI 单域名为了兼容 `gpt-image-*`，Nginx 将以下路径先转到生图兼容侧车：

```text
/v1/responses
/v1/chat/completions
  → subapi-image-compat（生图兼容侧车，内部监听 8328）
  → New API/SubAPI 后台
```

侧车职责有两类：

1. `gpt-image-*`：将错误打到 Responses/Chat 的生图请求转为 Images API。
2. 非生图模型：透传给 New API，同时做 `call_id` ≤ 64 等规范化。

## 根因

旧的非生图透传使用：

```python
resp.read()
```

即先把上游完整响应读完，再一次性写回客户端。对于 Codex++ 的 Responses streaming，这会破坏 SSE 实时分段：

```text
上游有流式输出
→ 侧车整包读取
→ 客户端最后一次性收到
```

所以 UI 没有打字效果，思考/流式状态也可能显示异常。

## 修复

在 `/root/subapi-image-compat/server.py` 增加：

```python
send_stream_passthrough(...)
```

对非生图模型且客户端请求 `stream=true` 或 `Accept: text/event-stream` 时：

- `urlopen()` 后不再 `resp.read()`；
- 使用 `resp.readline()` 按 SSE 行读取；
- 每行立即 `wfile.write()` + `flush()`；
- 响应头加 `X-Accel-Buffering: no`；
- 对 `BrokenPipeError` / `ConnectionResetError` 静默处理，避免客户端取消时误报 500。

伪形态：

```python
if not is_image_model(model):
    if client_wants_stream(data, headers):
        send_stream_passthrough(...)
    else:
        forward_raw(...)
```

## 验证

修复后：

- `python3 -m py_compile /root/subapi-image-compat/server.py` 通过；
- `systemctl restart subapi-image-compat` 后服务 active；
- 用户在 Codex++ 保持 Responses API 配置重新请求后确认：打字/分段效果恢复。

## 注意

- 不要把这个问题误判成 Codex++ 供应商协议没选 Responses；截图已确认选中 Responses API。
- Nginx 已配置 `proxy_buffering off`，但 8328 侧车整包读取同样会造成应用层缓冲。
- `/cursor/v1` 走的是 SubAPI 的 Cursor 翻译服务（内部监听 8327），与此处 `/v1` 的生图兼容侧车不同。
- 生图模型的官方 Images 映射仍保持原逻辑：不要添加 `Image generated for prompt` 等侧车文案。
