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
    test_no_lock_on_new_plan()
    test_short_plan_optimize_user_query_only()
    test_polluted_history_still_locks_session_root()
    test_fix_createplan_rewrites_name()
    print("OK all plan lock tests")