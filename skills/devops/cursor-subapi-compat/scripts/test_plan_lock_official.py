"""Official CLI-derived acceptance tests for Plan lock helpers."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", ROOT / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["subapi_server"] = mod
spec.loader.exec_module(mod)


def test_locks_first_createplan_name():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "CreatePlan",
                        "arguments": '{"name":"workspace-tidy-v3","plan":"# x"}',
                    }
                }
            ],
        },
        {"role": "user", "content": "更新计划当前的迭代简单点"},
    ]
    obj = {"messages": messages}
    assert mod.resolve_plan_lock_name(obj) == "workspace-tidy-v3"


def test_plan_md_path_fallback():
    messages = [
        {"role": "assistant", "content": "已在 workspace-tidy-v3_7e4c1294.plan.md 上完成压缩"},
        {"role": "user", "content": "更新计划当前的迭代简单点"},
    ]
    assert mod._first_plan_identity(messages) == "workspace-tidy-v3"


def test_chinese_plan_md_path_fallback():
    messages = [
        {"role": "assistant", "content": "Read C:\\Users\\admin\\.cursor\\plans\\示例开发计划_2534a917.plan.md L1-30"},
        {"role": "user", "content": "<user_query>更多点内容</user_query>"},
    ]
    assert mod._first_plan_identity(messages) == "示例开发计划"
    obj = {"messages": messages, "tools": [{"type": "function", "function": {"name": "CreatePlan"}}]}
    assert mod.resolve_plan_lock_name(obj) == "示例开发计划"
    assert mod.strip_createplan_tool_when_locked(obj, "示例开发计划")
    assert not any((t.get("function") or {}).get("name") == "CreatePlan" for t in obj["tools"])


def test_no_lock_on_new_plan():
    messages = [{"role": "user", "content": "新建计划，另起一个"}]
    obj = {"messages": messages}
    assert mod.resolve_plan_lock_name(obj) == ""


def test_short_plan_optimize_user_query_only():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "CreatePlan",
                        "arguments": '{"name":"short-plan","plan":"# x"}',
                    }
                }
            ],
        },
        {
            "role": "user",
            "content": (
                "<system_reminder>Do not create a new plan until user confirms.</system_reminder>\n"
                "<user_query>多点内容优化下</user_query>"
            ),
        },
    ]
    obj = {"messages": messages}
    assert mod._user_wants_new_plan(mod._latest_user_text(messages)) is False
    assert mod.resolve_plan_lock_name(obj) == "short-plan"


def test_polluted_history_still_locks_session_root():
    messages = []
    for name in ("workspace-tidy", "workspace-tidy-v3", "workspace-tidy-minimal-optimized"):
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "CreatePlan",
                            "arguments": json.dumps({"name": name, "plan": "# x"}),
                        }
                    }
                ],
            }
        )
    messages.append({"role": "user", "content": "优化v2版本"})
    obj = {"messages": messages}
    assert mod.resolve_plan_lock_name(obj) == "workspace-tidy"


def test_fix_createplan_rewrites_name() -> None:
    raw = '{"name":"short-plan-optimized","plan":"# v2"}'
    out = mod._fix_createplan_arguments_text(raw, "CreatePlan", "short-plan")
    assert json.loads(out)["name"] == "short-plan"


def test_sse_suppresses_createplan_when_locked() -> None:
    class FakeResp:
        def __init__(self, rows):
            self.rows = [r.encode("utf-8") for r in rows]
        def readline(self):
            return self.rows.pop(0) if self.rows else b""

    rows = [
        'data: {"type":"response.created","id":"resp_1","model":"gpt-5.4"}\n',
        'data: {"type":"response.output_item.added","output_index":0,"item":{"type":"function_call","name":"CreatePlan","call_id":"call_cp"}}\n',
        'data: {"type":"response.function_call_arguments.delta","output_index":0,"delta":"{\\"name\\":\\"示例开发计划 v2\\"}"}\n',
        'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"function_call","name":"CreatePlan","arguments":"{\\"name\\":\\"示例开发计划 v2\\"}"}}\n',
        'data: {"type":"response.completed"}\n',
    ]
    out = b"".join(mod.responses_sse_to_chat(FakeResp(rows), plan_lock_name="示例开发计划")).decode("utf-8")
    assert "CreatePlan" not in out
    assert '"tool_calls"' not in out
    assert '"finish_reason":"stop"' in out


def test_strip_createplan_when_locked():
    obj = {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "CreatePlan", "arguments": '{"name":"short-plan","plan":"#"}'}}
                ],
            },
            {"role": "user", "content": "继续简化下计划，不要新开计划"},
        ],
        "tools": [{"type": "function", "function": {"name": "CreatePlan"}}, {"type": "function", "function": {"name": "ReadFile"}}],
    }
    assert mod.strip_createplan_tool_when_locked(obj, "short-plan")
    names = [(t.get("function") or {}).get("name") for t in obj["tools"]]
    assert "CreatePlan" not in names
    assert "ReadFile" in names


if __name__ == "__main__":
    test_locks_first_createplan_name()
    test_plan_md_path_fallback()
    test_chinese_plan_md_path_fallback()
    test_no_lock_on_new_plan()
    test_short_plan_optimize_user_query_only()
    test_polluted_history_still_locks_session_root()
    test_fix_createplan_rewrites_name()
    test_sse_suppresses_createplan_when_locked()
    test_strip_createplan_when_locked()
    print("OK all plan lock tests")