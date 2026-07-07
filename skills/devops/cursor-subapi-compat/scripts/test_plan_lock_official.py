"""Official CLI-derived acceptance tests for Plan lock helpers."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", ROOT / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["subapi_server"] = mod
spec.loader.exec_module(mod)

def test_update_intent_locks_first_slug():
    messages = [
        {"role": "user", "content": "制定计划"},
        {"role": "assistant", "content": 'Created Plan workspace-tidy-v3'},
        {"role": "user", "content": "更新计划当前的迭代简单点"},
    ]
    obj = {"messages": messages, "tools": []}
    assert mod.resolve_plan_lock_name(obj) == "workspace-tidy-v3"

def test_plan_md_path_anchor():
    messages = [
        {"role": "assistant", "content": "已在 workspace-tidy-v3_7e4c1294.plan.md 上完成压缩"},
        {"role": "user", "content": "更新计划当前的迭代简单点"},
    ]
    obj = {"messages": messages}
    assert mod._thread_plan_anchor(messages, "更新计划当前的迭代简单点") == "workspace-tidy-v3"

def test_explicit_slug_in_user():
    messages = [{"role": "user", "content": "在 workspace-tidy-v3 上压缩"}]
    assert mod._thread_plan_anchor(messages, messages[0]["content"]) == "workspace-tidy-v3"

def test_no_lock_on_new_plan():
    messages = [{"role": "user", "content": "新建计划，另起一个"}]
    obj = {"messages": messages}
    assert mod.resolve_plan_lock_name(obj) == ""

def test_short_plan_optimize_user_query_only():
    """Cursor wraps user text; system reminder contains English 'new plan' — must not disable lock."""
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


def test_multi_plan_history_locks_last_active():
    import json
    messages = []
    for name in (
        "workspace-tidy",
        "workspace-tidy-v3",
        "workspace-tidy-minimal-optimized",
    ):
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
    messages.append({"role": "user", "content": "更新计划当前的迭代简单点"})
    obj = {"messages": messages}
    assert mod.resolve_plan_lock_name(obj) == "workspace-tidy-minimal-optimized"


def test_fix_createplan_rewrites_name() -> None:
    import json
    raw = '{"name":"workspace-tidy-minimal","plan":"# x"}'
    out = mod._fix_createplan_arguments_text(raw, "CreatePlan", "workspace-tidy-minimal-optimized")
    assert json.loads(out)["name"] == "workspace-tidy-minimal-optimized"

if __name__ == "__main__":
    test_update_intent_locks_first_slug()
    test_plan_md_path_anchor()
    test_explicit_slug_in_user()
    test_no_lock_on_new_plan()
    test_short_plan_optimize_user_query_only()
    test_multi_plan_history_locks_last_active()
    test_fix_createplan_rewrites_name()
    print("OK all plan lock tests")