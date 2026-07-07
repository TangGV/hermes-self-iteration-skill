# Cursor Plan official CLI acceptance (2026-07-08)

## Method

Run on Windows with official backend (not subapi3):

```text
cursor-agent.cmd --model composer-2.5 --mode plan
cursor-agent.cmd --mode plan --continue
```

Workspace: `C:\Users\t\workspace\cursor_plan_mode_compare\workspace_tidy_strict`

## Evidence table

| Case | User prompt | Official `createPlanToolCall.args.name` | In-place update? |
|------|-------------|----------------------------------------|------------------|
| A | PLANMODE_SENTINEL_A create | `PLANMODE_SENTINEL_A 工作区整理` | — |
| B | `--continue` modify A | **same** `PLANMODE_SENTINEL_A 工作区整理` | yes (same name) |
| C | force `workspace-tidy-v3` | `workspace-tidy-v3` | — |
| D | `--continue` compress v3 | **same** `workspace-tidy-v3` OR `editToolCall` on `.plan.md` | yes |
| E | GUI-like create | `workspace-tidy-strict` | — |
| F | `更新计划当前的迭代简单点` | **same** `workspace-tidy-strict` | yes |
| G | repeat F | **same** `workspace-tidy-strict` | yes |

## Conclusion for SubAPI bridge

1. Official never invents a new slug on update turns when session state is intact.
2. Update path may be `createPlanToolCall` (same `args.name`) or `editToolCall` on `*.plan.md`.
3. Custom API `/cursor/v1` often lacks CreatePlan in `tools` but still emits CreatePlan in stream — bridge must:
   - anchor **first** plan identity in thread (or explicit `workspace-tidy-*` in user text);
   - treat **更新计划** / **当前计划** as mandatory lock when anchor exists;
   - rewrite outbound `arguments.name` on SSE;
   - parse `workspace-tidy-*_hash.plan.md` paths from assistant text when history is truncated.

## Bridge unit test

```bash
python skills/devops/cursor-subapi-compat/scripts/test_plan_lock_official.py
```

## User acceptance on subapi3

After deploy, in **same** Plan thread say:

```text
更新计划当前的迭代简单点
```

Pass criteria:

- No new `Created Plan` card with a new slug.
- `journalctl -u subapi-cursor-compat` shows `plan-lock name=<first plan slug>`.
- Optional: `CURSOR_FULL_CAPTURE` body shows rewritten `name` in streamed CreatePlan args.