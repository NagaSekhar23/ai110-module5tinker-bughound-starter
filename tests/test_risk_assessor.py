import pytest

from reliability.risk_assessor import assess_risk


def test_no_fix_is_high_risk():
    risk = assess_risk(
        original_code="print('hi')\n",
        fixed_code="",
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print"}],
    )
    assert risk["level"] == "high"
    assert risk["should_autofix"] is False
    assert risk["score"] == 0


def test_low_risk_when_minimal_change_and_low_severity():
    original = "import logging\n\ndef add(a, b):\n    return a + b\n"
    fixed = "import logging\n\ndef add(a, b):\n    return a + b\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "minor"}],
    )
    assert risk["level"] in ("low", "medium")  # depends on scoring rules
    assert 0 <= risk["score"] <= 100


def test_high_severity_issue_drives_score_down():
    original = "def f():\n    try:\n        return 1\n    except:\n        return 0\n"
    fixed = "def f():\n    try:\n        return 1\n    except Exception as e:\n        return 0\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Reliability", "severity": "High", "msg": "bare except"}],
    )
    assert risk["score"] <= 60
    assert risk["level"] in ("medium", "high")


def test_missing_return_is_penalized():
    original = "def f(x):\n    return x + 1\n"
    fixed = "def f(x):\n    x + 1\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[],
    )
    assert risk["score"] < 100
    assert any("Return" in r or "return" in r for r in risk["reasons"])


# ----------------------------
# Part 3: signature-change signal
# ----------------------------
def test_safe_minimal_fix_keeps_low_risk_and_autofix():
    code = "def f(x):\n    return x + 1\n"
    risk = assess_risk(code, code, [])
    assert risk["level"] == "low"
    assert risk["should_autofix"] is True
    assert risk["reasons"] == ["No significant risks detected."]


def test_changed_signature_adds_risk_and_blocks_autofix():
    risk = assess_risk(
        "def f(x):\n    return x + 1\n",
        "def f(x, y):\n    return x + 1\n",
        [],
    )
    assert risk["score"] == 70
    assert risk["level"] == "medium"
    assert risk["should_autofix"] is False
    assert any("signature" in r for r in risk["reasons"])


def test_signature_whitespace_only_change_is_not_flagged():
    risk = assess_risk("def f(a,b):\n    return a\n", "def f(a, b):\n    return a\n", [])
    assert risk["should_autofix"] is True


def test_removed_function_is_flagged():
    original = "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
    fixed = "def a():\n    return 1\n\ndef c():\n    return 3\n\n# gap\n# gap\n"
    risk = assess_risk(original, fixed, [])
    assert any("b" in r and "signature" in r for r in risk["reasons"])
    assert risk["should_autofix"] is False


def test_destructive_rewrite_is_not_penalized_twice_for_signature():
    original = "def f(x):\n    a = 1\n    b = 2\n    return x\n"
    fixed = "pass\n"
    risk = assess_risk(original, fixed, [])
    assert not any("signature" in r for r in risk["reasons"])
    assert any("shorter" in r for r in risk["reasons"])


def test_removed_return_still_triggers_caution():
    risk = assess_risk("def f(x):\n    return x + 1\n", "def f(x):\n    x + 1\n", [])
    assert any("Return" in r for r in risk["reasons"])
    assert risk["should_autofix"] is False


@pytest.mark.parametrize(
    "score_issues, expected_level",
    [([], "low"), ([{"severity": "High"}], "medium"), ([{"severity": "High"}] * 2, "high")],
)
def test_thresholds_and_autofix_decision_are_consistent(score_issues, expected_level):
    code = "def f(x):\n    return x\n"
    risk = assess_risk(code, code, score_issues)
    assert risk["level"] == expected_level
    assert risk["should_autofix"] == (risk["level"] == "low")


def test_existing_rules_unchanged_for_bare_except_rewrite():
    original = "def f():\n    try:\n        return 1\n    except:\n        return 0\n"
    fixed = "def f():\n    try:\n        return 1\n    except Exception as e:\n        return 0\n"
    risk = assess_risk(original, fixed, [{"severity": "High"}])
    assert risk["score"] == 55  # 100 - 40 (high) - 5 (bare except modified)


# ----------------------------
# Part 4: syntax-validity guardrail
# ----------------------------
def test_syntactically_invalid_fix_is_hard_blocked_even_with_good_score():
    original = "def f():\n    return 1\n"
    fixed = "def f():\n    return 1 +\n"  # all other rules pass
    risk = assess_risk(original, fixed, [{"severity": "Low"}])
    assert risk["should_autofix"] is False
    assert risk["level"] == "high"
    assert risk["guardrail_blocks"]
    assert any("not valid Python" in r for r in risk["reasons"])


def test_valid_fix_has_no_guardrail_blocks():
    code = "def f():\n    return 1\n"
    assert assess_risk(code, code, [])["guardrail_blocks"] == []
