# Cursor 设置核对清单

按顺序勾选，避免「服务端正常但 Cursor 没打到」。

## 1. Cursor 设置

- [ ] **Settings → Models → OpenAI API Key**：已填完整 `sk-...`（SubAPI 面板复制）
- [ ] **Override OpenAI Base URL** 已开启
- [ ] Base URL  exactly：`https://subapi.aigcfast.com/cursor/v1`（末尾可无 `/`，但不要写成 `/v1`）
- [ ] 未混用 OpenAI 账号登录 + 自定义 Key 导致校验冲突（若报错 `ERROR_BAD_USER_API_KEY` 且服务器无日志，优先怀疑此项）
- [ ] 已 **新开** 一个 Chat/Agent 会话测试
- [ ] 可选：Reload Window 后再测

## 2. 模型选择

- [ ] 模型在 `GET https://subapi.aigcfast.com/cursor/v1/models` 列表中存在
- [ ] 未选 `gpt-image-2` 当对话模型（生图走 `/v1/images/generations`）

## 3. 服务端（仅当客户端仍失败）

- [ ] `systemctl is-active subapi-cursor-compat` → active
- [ ] `ss -ltnp | grep 8327` 有 python3 监听
- [ ] `subapi.aigcfast.com.conf` 中 `/cursor/v1/` 指向 `127.0.0.1:8327`（不是误指 8317 除非刻意 CPA 方案）
- [ ] 测试时 access.log 出现 `POST .../cursor/v1/chat/completions`

## 4. 与 Postman/curl 测试区分

- Postman 测 **生图**：`https://subapi.aigcfast.com/v1/images/generations`（不是 cursor 前缀）
- Postman 测 **Cursor 兼容**：`https://subapi.aigcfast.com/cursor/v1/chat/completions`，body 用 `input` 而非仅 `messages`