"""Part 2: strict validation of LLM analyzer output (offline, scripted client)."""
import json

import pytest

from bughound_agent import BugHoundAgent

CODE = "def f():\n    print('hi')\n    return True\n"
GOOD = [{"type": "Reliability", "severity": "high", "msg": "Division may fail on zero."}]


class ScriptedClient:
    """Returns a fixed analyzer response; returns the original-ish code for the fixer."""

    def __init__(self, analyzer_response):
        self.analyzer_response = analyzer_response

    def complete(self, system_prompt, user_prompt):
        if "Return ONLY valid JSON" in system_prompt:
            return self.analyzer_response
        return "def f():\n    return True\n"


def run(response):
    return BugHoundAgent(client=ScriptedClient(response)).run(CODE)


def fallback_logged(result):
    return any("rejected" in e["message"] and "Falling back to heuristics" in e["message"] for e in result["logs"])


def test_valid_output_is_accepted_and_normalized():
    result = run(json.dumps(GOOD))
    assert result["issues"] == [{"type": "Reliability", "severity": "High", "msg": "Division may fail on zero."}]
    assert not fallback_logged(result)


def test_valid_empty_array_means_no_issues_not_fallback():
    result = run("[]")
    assert result["issues"] == []
    assert not fallback_logged(result)


def test_json_embedded_in_prose_is_still_validated_and_accepted():
    result = run("Here you go: " + json.dumps(GOOD))
    assert result["issues"][0]["severity"] == "High"


@pytest.mark.parametrize(
    "response, reason",
    [
        ("not json at all", "not parseable"),
        ("", "empty response"),
        ("   \n", "empty response"),
        ('{"type": "x"}', "not parseable"),
        (json.dumps([{"type": "A", "severity": "High"}]), "missing required field 'msg'"),
        (json.dumps([{"severity": "High", "msg": "something wrong"}]), "missing required field 'type'"),
        (json.dumps([{"type": 1, "severity": "High", "msg": "something wrong"}]), "must be a string"),
        (json.dumps([{"type": "A", "severity": 3, "msg": "something wrong"}]), "must be a string"),
        (json.dumps([{"type": "A", "severity": "Catastrophic", "msg": "something wrong"}]), "invalid severity"),
        (json.dumps([{"type": "A", "severity": "High", "msg": ""}]), "too-short"),
        (json.dumps([{"type": " ", "severity": "High", "msg": "something wrong"}]), "empty 'type'"),
        (json.dumps(["just a string"]), "not an object"),
        (json.dumps(GOOD + [{"type": "A"}]), "missing required field"),  # one bad item rejects all
    ],
)
def test_invalid_output_falls_back_to_heuristics_with_reason(response, reason):
    result = run(response)
    # Heuristic analyzer found the print statement => fallback really happened.
    assert any(i["type"] == "Code Quality" for i in result["issues"])
    assert fallback_logged(result)
    assert any(reason in e["message"] for e in result["logs"])


def test_client_exception_never_crashes_the_agent():
    class Boom:
        def complete(self, system_prompt, user_prompt):
            raise RuntimeError("network down")

    result = BugHoundAgent(client=Boom()).run(CODE)
    assert result["issues"]
    assert any("API Error" in e["message"] for e in result["logs"])
