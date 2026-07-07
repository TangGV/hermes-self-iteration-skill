# Cursor Plan mode create/update behavior

## Root cause pattern

Cursor Plan mode does not use a separate `UpdatePlan` tool in the observed Composer 2.5 CLI flow. Both creating and updating a plan use the same `CreatePlan` tool / `createPlanRequestQuery`.

Official Cursor Agent CLI behavior observed with `--model composer-2.5 --mode plan --continue`:

- first request used `createPlanToolCall` with `args.name = "PLANMODE_SENTINEL_A Demo"`;
- update request also used `createPlanToolCall` with the **same** `args.name = "PLANMODE_SENTINEL_A Demo"`;
- only the plan title/body changed (`UPDATED_B`, Python CLI details);
- this is treated as an in-place update by Cursor's plan manager.

Therefore, if the self-hosted `/cursor/v1` path keeps producing new plans, the likely failure is not "missing UpdatePlan tool". The likely failure is that the model emits `CreatePlan` with a different `args.name` during an update turn, so Cursor's plan manager treats it as a distinct plan.

## Fix in SubAPI Cursor bridge

The bridge now scans incoming chat history for prior `CreatePlan` tool calls and extracts the latest existing plan `args.name`. If the newest user turn asks to modify/update/revise/iterate the existing/original plan and the tool list includes a plan creation tool, the bridge prepends a compact compatibility system instruction:

```text
Cursor Plan compatibility instruction: this conversation already has an existing plan named '<name>'. If the user asks to modify/update/revise/iterate the existing or original plan, call the plan creation tool with exactly the same args.name value above and the full updated plan content. Do not invent a new plan name, do not append suffixes to args.name, and do not create a second plan. Only the plan title/body may change.
```

This preserves official Cursor semantics: use `CreatePlan`, but keep `args.name` stable.

If the conversation already contains a prior `CreatePlan` tool call, the bridge now **always** injects the compatibility nudge on follow-up turns (unless the user explicitly asks for a new plan). Keywords like **优化** are included; you do not need to say “不要新建”.

On the response path, when a plan lock name is active, the bridge also **rewrites outgoing `CreatePlan` tool `arguments.name`** to the locked plan title so Cursor’s plan manager updates in place even if the model invents a new name.

For plan panel typing effect, large upstream text/tool-argument chunks are split into smaller ChatCompletions SSE deltas (~24 chars) before forwarding to Cursor.

## Verification command

Official CLI comparison:

```bash
cd /c/Users/t/workspace/cursor_plan_mode_compare
"/c/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd" \
  --print --trust --model composer-2.5 --mode plan \
  --output-format stream-json --stream-partial-output \
  "PLANMODE_SENTINEL_A：请为这个小项目制定一个三步计划，计划标题必须包含 PLANMODE_SENTINEL_A。不要修改文件。" \
  | tee plan_a.jsonl

"/c/Users/t/AppData/Local/cursor-agent/cursor-agent.cmd" \
  --print --trust --model composer-2.5 --mode plan --continue \
  --output-format stream-json --stream-partial-output \
  "PLANMODE_SENTINEL_B：请修改刚才已有的 PLANMODE_SENTINEL_A 计划：保留原三步结构，但把第二步改成 Python CLI 方案，并在标题追加 UPDATED_B。要求修改原计划，不要新建第二个计划。" \
  | tee plan_b_continue.jsonl
```

Parse plan tool calls:

```bash
python - <<'PY'
import json
from pathlib import Path
for fn in ['plan_a.jsonl','plan_b_continue.jsonl']:
    print('\n##', fn)
    for line in Path(fn).read_text(encoding='utf-8', errors='ignore').splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('type') == 'tool_call':
            tc = o.get('tool_call') or {}
            cp = tc.get('createPlanToolCall')
            if cp:
                args = cp.get('args') or {}
                print(o.get('subtype'), 'name=', args.get('name'), 'updated=', 'UPDATED_B' in str(args.get('plan')))
PY
```

Expected official behavior:

```text
plan_a.jsonl: name=PLANMODE_SENTINEL_A Demo updated=False
plan_b_continue.jsonl: name=PLANMODE_SENTINEL_A Demo updated=True
```

Bridge unit check:

```bash
python - <<'PY'
import importlib.util, json
p='skills/devops/cursor-subapi-compat/scripts/subapi-server.py'
spec=importlib.util.spec_from_file_location('subapi_server_test', p)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
obj={
 'model':'gpt-5.5','stream':True,
 'tools':[{'type':'function','function':{'name':'CreatePlan','parameters':{}}}],
 'messages':[
   {'role':'assistant','tool_calls':[{'id':'call_old','type':'function','function':{'name':'CreatePlan','arguments':json.dumps({'name':'Existing Plan','plan':'old'})}}]},
   {'role':'tool','tool_call_id':'call_old','content':'ok'},
   {'role':'user','content':'请修改原计划，不要新建'}
 ]
}
resp, changed = mod.chat_to_responses_payload(obj)
print(resp.get('metadata'))
print(resp['input'][0]['content'])
PY
```

Expected:

```text
{'cursor_plan_update_name': 'Existing Plan'}
Cursor Plan compatibility instruction: this conversation already has an existing plan named 'Existing Plan'...
```

## Deployment notes

Deploy only the Cursor translation service, not New API/CPA:

```bash
scp skills/devops/cursor-subapi-compat/scripts/subapi-server.py root@82.158.91.156:/root/subapi-cursor-compat/server.py
ssh root@82.158.91.156 'cd /root/subapi-cursor-compat && python3 -m py_compile server.py && systemctl restart subapi-cursor-compat && systemctl is-active subapi-cursor-compat'
```

If OpenSSH reports `Connection timed out during banner exchange`, first distinguish a real host outage from an OpenSSH/client-path flake:

```bash
python - <<'PY'
import socket
s=socket.create_connection(('82.158.91.156', 22), timeout=8)
s.settimeout(5)
print(s.recv(80))
s.close()
PY
```

If the raw TCP banner is returned but `ssh/scp` still time out, a Paramiko+SFTP deploy path can be used instead of waiting or touching unrelated services:

```python
import paramiko, pathlib
host='82.158.91.156'
key=paramiko.Ed25519Key.from_private_key_file(r'C:\Users\t\.ssh\id_ed25519')
cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(host, username='root', pkey=key, timeout=10, banner_timeout=10, auth_timeout=10, look_for_keys=False, allow_agent=False)

def run(cmd):
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=60)
    out, err = stdout.read().decode(), stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    if rc: raise RuntimeError((cmd, rc, out, err))
    return out

run('cd /root/subapi-cursor-compat && cp server.py server.py.bak-$(date +%Y%m%d-%H%M%S)')
sftp=cli.open_sftp()
sftp.put(r'C:\Users\t\AppData\Local\hermes\skills\devops\cursor-subapi-compat\scripts\subapi-server.py', '/root/subapi-cursor-compat/server.py')
sftp.close()
run('cd /root/subapi-cursor-compat && python3 -m py_compile server.py')
run('systemctl restart subapi-cursor-compat && sleep 2 && systemctl is-active subapi-cursor-compat')
cli.close()
```

Still do not restart New API/CPA or do broad host recovery for this fix; the scope is only `subapi-cursor-compat`.
