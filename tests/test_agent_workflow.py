from bughound_agent import BugHoundAgent
from llm_client import MockClient


def test_workflow_runs_in_offline_mode_and_returns_shape():
    agent = BugHoundAgent(client=None)  # heuristic-only
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert isinstance(result, dict)
    assert "issues" in result
    assert "fixed_code" in result
    assert "risk" in result
    assert "logs" in result

    assert isinstance(result["issues"], list)
    assert isinstance(result["fixed_code"], str)
    assert isinstance(result["risk"], dict)
    assert isinstance(result["logs"], list)
    assert len(result["logs"]) > 0


def test_offline_mode_detects_print_issue():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])


def test_offline_mode_proposes_logging_fix_for_print():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    fixed = result["fixed_code"]
    assert "logging" in fixed
    assert "logging.info(" in fixed


def test_mock_client_forces_llm_fallback_to_heuristics_for_analysis():
    # MockClient returns non-JSON for analyzer prompts, so agent should fall back.
    agent = BugHoundAgent(client=MockClient())
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])
    # Ensure we logged the fallback path
    assert any("Falling back to heuristics" in entry.get("message", "") for entry in result["logs"])


# ----------------------------
# Part 4: guardrail + edge cases (all offline)
# ----------------------------
class BrokenFixerClient:
    """Valid analyzer JSON, but the fixer returns code with a syntax error."""

    def complete(self, system_prompt, user_prompt):
        if "Return ONLY valid JSON" in system_prompt:
            return '[{"type": "Code Quality", "severity": "Low", "msg": "print used in code"}]'
        return "def f():\n    return 1 +\n"


def test_regression_syntax_broken_llm_fix_is_never_autoapplied():
    # Without the syntax guardrail this scored 95 / low / auto-fix YES.
    result = BugHoundAgent(client=BrokenFixerClient()).run("def f():\n    print(1)\n    return 1\n")
    assert result["risk"]["should_autofix"] is False
    assert result["risk"]["level"] == "high"
    assert any(e["step"] == "TEST" and "GUARDRAIL" in e["message"] for e in result["logs"])
    assert any("Human review recommended" in e["message"] for e in result["logs"])


def test_invalid_python_input_is_not_autofixed():
    result = BugHoundAgent(client=None).run("def f(:\n    print('x')\n")
    assert result["risk"]["should_autofix"] is False


def test_empty_file_does_not_crash_and_is_not_autofixed():
    result = BugHoundAgent(client=None).run("")
    assert result["issues"] == []
    assert result["risk"]["should_autofix"] is False


def test_comments_only_file_has_no_issues_and_is_safe():
    result = BugHoundAgent(client=None).run("# just a comment\n")
    assert result["issues"] == []
    assert result["risk"]["should_autofix"] is True


def test_cleanish_sample_is_clean():
    code = open("sample_code/cleanish.py").read()
    result = BugHoundAgent(client=None).run(code)
    assert result["issues"] == []
    assert result["fixed_code"] == code


def test_mixed_issues_sample_requires_human_review_with_mock_client():
    code = open("sample_code/mixed_issues.py").read()
    result = BugHoundAgent(client=MockClient()).run(code)
    assert len(result["issues"]) == 3
    assert result["risk"]["should_autofix"] is False


def test_unexpected_fixer_response_prose_is_not_autoapplied():
    class ProseFixer:
        def complete(self, system_prompt, user_prompt):
            if "Return ONLY valid JSON" in system_prompt:
                return '[{"type": "Code Quality", "severity": "Low", "msg": "print used in code"}]'
            return "Sure! I would change the print to logging, hope that helps."

    result = BugHoundAgent(client=ProseFixer()).run("def f():\n    print(1)\n    return 1\n")
    assert result["risk"]["should_autofix"] is False


# ----------------------------
# Honest reporting of which engine ran
# ----------------------------
def test_offline_run_reports_heuristic_source_and_never_mentions_llm():
    result = BugHoundAgent(client=None).run("def f():\n    print(1)\n    return 1\n")
    assert result["analysis_source"] == "heuristic"
    assert result["fix_source"] == "heuristic"
    assert not any("LLM" in e["message"] for e in result["logs"])


def test_llm_fallback_reports_heuristic_source():
    result = BugHoundAgent(client=MockClient()).run("def f():\n    print(1)\n    return 1\n")
    assert result["analysis_source"] == "heuristic"


def test_valid_llm_output_reports_llm_source():
    class Good:
        def complete(self, system_prompt, user_prompt):
            if "Return ONLY valid JSON" in system_prompt:
                return '[{"type": "Code Quality", "severity": "Low", "msg": "print used in code"}]'
            return "import logging\n\ndef f():\n    logging.info(1)\n    return 1\n"

    result = BugHoundAgent(client=Good()).run("def f():\n    print(1)\n    return 1\n")
    assert result["analysis_source"] == "llm"
    assert result["fix_source"] == "llm"
