# Composer 2.5 CLI full-flow test plan

## Purpose

Use this plan to repeatedly test local Cursor Agent CLI with **Composer 2.5** and correlate local CLI behavior with the self-hosted SubAPI Cursor bridge (`/cursor/v1`) monitoring.

The goal is not only to prove that the CLI can answer. The goal is to determine, with evidence:

1. whether the local Cursor Agent CLI is functional;
2. whether `--model composer-2.5` is actually selected;
3. whether file read/write/shell/test tools work;
4. whether large-context reads work;
5. whether the traffic hits the self-hosted `/cursor/v1` bridge or the official Cursor backend;
6. when UI/agent appears stuck, whether the delay is local tool execution, upstream headers, first meaningful output, client disconnect, HTTP error, or empty upstream completion.

## Scope

Test target:

```text
Local Windows Cursor Agent CLI
C:\Users\t\AppData\Local\cursor-agent\cursor-agent.cmd
```

Primary model:

```text
composer-2.5
```

Optional comparison model:

```text
composer-2.5-fast
```

Self-hosted SubAPI route to correlate when traffic reaches it:

```text
https://subapi3.aigcfast.com/cursor/v1
```

## Safety rules

- Run in an isolated disposable workspace only.
- Do not run tests inside an active production repo unless explicitly testing that repo.
- Use `--trust` and `--force` only in the isolated test workspace.
- Do not paste API keys into logs or prompts.
- Do not assume Cursor CLI traffic hits `/cursor/v1`; verify with bridge logs.
- Do not treat a successful official Composer 2.5 CLI run as proof that SubAPI `/cursor/v1` is healthy unless VPS bridge logs show matching `active-audit`/`flow-audit` entries.

## Prerequisites

### 1. Confirm CLI is installed and logged in

```bash
"/c/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd" status
"/c/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd" models | grep -E 'composer-2.5|gpt-5.5'
```

Expected:

```text
✓ Logged in as ...
composer-2.5 - Composer 2.5 (current)
composer-2.5-fast - Composer 2.5 Fast (default)
```

### 2. Confirm bridge monitoring is live

On VPS3:

```bash
systemctl is-active subapi-cursor-compat
journalctl -u subapi-cursor-compat --since '5 minutes ago' --no-pager \
  | grep -E 'active-audit|flow-audit|resp-audit|slow-audit|error-audit|exception-audit' \
  | tail -40
```

Expected:

- service is `active`;
- logs contain monitoring events when `/cursor/v1` traffic is present.

## Test workspace setup

Use a fresh directory:

```bash
rm -rf /c/Users/t/workspace/cursor_cli_composer25_test
mkdir -p /c/Users/t/workspace/cursor_cli_composer25_test
cd /c/Users/t/workspace/cursor_cli_composer25_test
printf 'hello composer cli\n' > input.txt
```

Create a small Python bug fixture:

```bash
cat > test_math.py <<'PY'
def add(a, b):
    # BUG: should return sum
    return a - b


def mul(a, b):
    return a * b
PY

cat > test_math_pytest.py <<'PY'
import test_math


def test_add():
    assert test_math.add(2, 3) == 5


def test_mul():
    assert test_math.mul(4, 5) == 20
PY
```

Create a large-context file with a sentinel near the end:

```bash
python - <<'PY'
from pathlib import Path
p = Path('BIG_CONTEXT.txt')
sentinel = 'CURSOR_CLI_COMPOSER25_SENTINEL_20260707'
line = '0123456789abcdef The quick brown fox jumps over the lazy dog. 测试长上下文。\n'
size = 0
n = 0
with p.open('w', encoding='utf-8') as f:
    while size < 4_800_000:
        chunk = f'{n:06d} {line}'
        f.write(chunk)
        size += len(chunk.encode('utf-8'))
        n += 1
    f.write('\n' + sentinel + '\n')
print(p, p.stat().st_size, 'lines', n + 2, sentinel)
PY
```

Expected size: about `4.8 MB`.

## Standard runner

Create `run_composer25_tests.py` in the workspace:

```python
import subprocess, time, json, pathlib

WORK = pathlib.Path(r'C:/Users/t/workspace/cursor_cli_composer25_test')
AGENT = r'C:/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd'
RESULTS = []


def run(name, prompt, timeout=360, force=False, mode=None, model='composer-2.5'):
    cmd = [AGENT, '--print', '--trust', '--model', model, '--output-format', 'text']
    if force:
        cmd.append('--force')
    if mode:
        cmd += ['--mode', mode]
    cmd.append(prompt)

    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(WORK), text=True, capture_output=True, timeout=timeout)
        elapsed = time.time() - t0
        res = {
            'name': name,
            'model': model,
            'exit': p.returncode,
            'elapsed_s': round(elapsed, 2),
            'stdout': p.stdout[-6000:],
            'stderr': p.stderr[-3000:],
        }
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - t0
        res = {
            'name': name,
            'model': model,
            'exit': 'TIMEOUT',
            'elapsed_s': round(elapsed, 2),
            'stdout': (e.stdout or '')[-6000:] if isinstance(e.stdout, str) else str(e.stdout)[-6000:],
            'stderr': (e.stderr or '')[-3000:] if isinstance(e.stderr, str) else str(e.stderr)[-3000:],
        }

    RESULTS.append(res)
    print('\n===== %s =====' % name)
    print(json.dumps({k: v for k, v in res.items() if k not in ('stdout', 'stderr')}, ensure_ascii=False))
    print('STDOUT_TAIL:\n', res['stdout'])
    print('STDERR_TAIL:\n', res['stderr'])
    (WORK / f'result_{name}.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    return res


run('01_smoke_ask', '只回答一行：COMPOSER25_SMOKE_OK', timeout=180)

run(
    '02_file_write',
    '读取 input.txt，把内容转成大写，写入 output_upper.txt。完成后只回答文件路径和内容。',
    timeout=240,
    force=True,
)

run(
    '03_code_fix_pytest',
    '请检查 test_math.py 和 test_math_pytest.py，修复 add 函数 bug，然后运行 python -m pytest -q test_math_pytest.py 验证。最后简短报告修改和测试结果。',
    timeout=360,
    force=True,
)

run(
    '04_big_context',
    '请读取 BIG_CONTEXT.txt，确认文件末尾 sentinel 是否存在，只回答 sentinel 原文、文件大约字节数、你是否能定位到末尾。不要全文输出。',
    timeout=420,
    force=True,
)

run(
    '05_final_workspace_audit',
    '检查当前工作区生成的文件列表，确认 output_upper.txt 是否存在、test_math.py 是否已修复、BIG_CONTEXT.txt 是否存在。可以使用 shell/read 工具。最后用三行中文总结。',
    timeout=300,
    force=True,
)

(WORK / 'all_results.json').write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding='utf-8')
print('\nALL_RESULTS_JSON=', WORK / 'all_results.json')
```

Run it:

```bash
python run_composer25_tests.py
```

## Required test cases and pass criteria

| ID | Test | Pass criteria | Failure signals |
|---|---|---|---|
| 01 | Smoke ask | stdout contains `COMPOSER25_SMOKE_OK`; exit 0 | timeout, auth error, no output |
| 02 | File read/write | `output_upper.txt` exists and contains `HELLO COMPOSER CLI` | no file, wrong content, permission prompt loop |
| 03 | Code fix + pytest | `test_math.py` uses `return a + b`; pytest shows `2 passed` | did not edit, tests fail, shell denied |
| 04 | Large context | returns sentinel `CURSOR_CLI_COMPOSER25_SENTINEL_20260707` and approx 4.8MB | cannot locate tail, hallucinated sentinel, timeout |
| 05 | Workspace audit | confirms generated files and repaired code | misses files, wrong state |

## Stream-json model verification

Run a separate probe to prove the CLI selected Composer 2.5:

```bash
"/c/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd" \
  --print --trust --model composer-2.5 \
  --output-format stream-json --stream-partial-output \
  "只回答：STREAM_JSON_MODEL_PROBE_OK" \
  | tee stream_probe.jsonl
```

Expected init event:

```json
{"type":"system","subtype":"init","model":"Composer 2.5"}
```

Expected result event:

```json
{"type":"result","subtype":"success","result":"STREAM_JSON_MODEL_PROBE_OK"}
```

Record:

- `duration_ms`
- `duration_api_ms`
- `usage.inputTokens`
- `usage.outputTokens`
- `usage.cacheReadTokens`

## Independent verification after the run

```bash
cd /c/Users/t/workspace/cursor_cli_composer25_test
python -m pytest -q test_math_pytest.py
python - <<'PY'
from pathlib import Path
for name in ['output_upper.txt', 'test_math.py', 'BIG_CONTEXT.txt', 'all_results.json', 'stream_probe.jsonl']:
    p = Path(name)
    print(name, p.exists(), p.stat().st_size if p.exists() else None)
    if name in ['output_upper.txt', 'test_math.py'] and p.exists():
        print(p.read_text())
PY
```

Expected:

```text
2 passed
output_upper.txt True
HELLO COMPOSER CLI
test_math.py True
return a + b
BIG_CONTEXT.txt True ~4.8MB
```

## Bridge correlation

### 1. Check whether CLI hit self-hosted `/cursor/v1`

On VPS3:

```bash
journalctl -u subapi-cursor-compat --since '30 minutes ago' --no-pager \
  | grep -E 'active-audit|flow-audit|resp-audit|slow-audit|error-audit|exception-audit' \
  | tail -160
```

If no new logs appear during the CLI run, the CLI likely used official Cursor backend rather than the self-hosted Override path. That is an important result, not a failure of the CLI test.

### 2. For matching bridge requests

For each matching `req_id`, record:

- `raw_len`
- `model`
- `reasoning`
- `tools`
- `upstream_request_id`
- `upstream_open_ms`
- `first_chunk_ms`
- `first_output_ms`
- `elapsed_ms`
- `tool_names`
- `status`

Join one bridge request:

```bash
REQ='...'
journalctl -u subapi-cursor-compat --since '30 minutes ago' --no-pager | grep "$REQ"
```

Join New API by upstream request ID:

```bash
RID='202607...'
docker logs --since 30m new-api 2>&1 | grep "$RID"
```

## Interpretation matrix

| Observation | Interpretation | Next action |
|---|---|---|
| CLI success, no `/cursor/v1` logs | Official Composer CLI path works; does not prove self-hosted bridge health | Test Cursor IDE Override separately or use TrafficLens |
| `status=ok`, `has_tool_calls=True`, `finish_seen=tool_calls` | Normal multi-round Agent tool loop | If UI looks stuck, inspect `first_output_ms` / local tool execution |
| High `upstream_open_ms` | Slow before upstream stream opens; queue/provider/network/New API path | Join `upstream_request_id` in New API logs |
| Low `upstream_open_ms`, high `first_output_ms` | Provider/model thinking latency after stream open | Compare model/reasoning/raw_len/cache hit |
| `empty_upstream=True` | Upstream returned no useful text/tool output | Use empty-upstream runbook; inspect New API usage/logs |
| `write_broken=True` | Cursor/client disconnected while bridge was streaming | Correlate nginx `499` and New API `client_gone` |
| `error-audit upstream_status=401/403` | Auth/key issue | Check key/base and token status |
| `error-audit upstream_status=429` | Real rate-limit/upstream quota | Check New API/channel/user/token quota |
| CLI timeout but bridge request still active | Long-running upstream/model/tool loop | Wait or inspect active connection; avoid killing services first |

## Recommended report format

Use this short table in user-facing reports:

| Test | Result | Time | Evidence |
|---|---:|---:|---|
| Smoke | ✅/❌ | s | stdout marker |
| File write | ✅/❌ | s | path + content |
| Code fix + pytest | ✅/❌ | s | pytest output |
| Big context | ✅/❌ | s | sentinel + size |
| Workspace audit | ✅/❌ | s | file list |
| Stream-json model | ✅/❌ | s | `model=Composer 2.5`, usage |

Then include bridge summary:

| Metric | Value |
|---|---|
| Hit `/cursor/v1` | yes/no/partial |
| Slow requests | count + max `elapsed_ms` |
| Empty upstream | count + req_id |
| Write broken | count + req_id |
| HTTP errors | status + req_id |
| Worst first_output_ms | req_id + value |
| Worst upstream_open_ms | req_id + value |

## Cleanup

The workspace is disposable:

```bash
rm -rf /c/Users/t/workspace/cursor_cli_composer25_test
```

Keep `all_results.json`, `stream_probe.jsonl`, and selected bridge log snippets if they are needed for a bug report.
