import ast
import re
from typing import Dict, List

# Matches `def name(params)` (single-line headers). Used to compare signatures.
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE)

# Highest score allowed when a hard guardrail blocks auto-fix (maps to "high").
GUARDRAIL_SCORE_CAP = 39


def _function_signatures(code: str) -> Dict[str, str]:
    """Map function name -> parameter list with whitespace removed."""
    return {name: re.sub(r"\s+", "", params) for name, params in _DEF_RE.findall(code)}


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except (SyntaxError, ValueError):
        return False


def assess_risk(
    original_code: str,
    fixed_code: str,
    issues: List[Dict[str, str]],
) -> Dict[str, object]:
    """
    Simple, explicit risk assessment used as a guardrail layer.

    Returns a dict with:
    - score: int from 0 to 100
    - level: "low" | "medium" | "high"
    - reasons: list of strings explaining deductions
    - should_autofix: bool
    """

    reasons: List[str] = []
    score = 100

    if not fixed_code.strip():
        return {
            "score": 0,
            "level": "high",
            "reasons": ["No fix was produced."],
            "should_autofix": False,
            "guardrail_blocks": [],
        }

    original_lines = original_code.strip().splitlines()
    fixed_lines = fixed_code.strip().splitlines()

    # ----------------------------
    # Issue severity based risk
    # ----------------------------
    for issue in issues:
        severity = str(issue.get("severity", "")).lower()

        if severity == "high":
            score -= 40
            reasons.append("High severity issue detected.")
        elif severity == "medium":
            score -= 20
            reasons.append("Medium severity issue detected.")
        elif severity == "low":
            score -= 5
            reasons.append("Low severity issue detected.")

    # ----------------------------
    # Structural change checks
    # ----------------------------
    much_shorter = len(fixed_lines) < len(original_lines) * 0.5
    if much_shorter:
        score -= 20
        reasons.append("Fixed code is much shorter than original.")

    # A changed or dropped function signature can break every caller.
    # Skipped when the "much shorter" rule already fired, so one destructive
    # rewrite (e.g. the whole function deleted) is not penalized twice.
    if not much_shorter:
        before = _function_signatures(original_code)
        after = _function_signatures(fixed_code)
        changed = sorted(n for n, params in before.items() if after.get(n) != params)
        if changed:
            score -= 30
            reasons.append(
                "Function signature changed or function removed: "
                + ", ".join(changed)
                + ". Callers may break."
            )

    if "return" in original_code and "return" not in fixed_code:
        score -= 30
        reasons.append("Return statements may have been removed.")

    if "except:" in original_code and "except:" not in fixed_code:
        # This is usually good, but still risky.
        score -= 5
        reasons.append("Bare except was modified, verify correctness.")

    # ----------------------------
    # Hard guardrail: unverifiable output is never auto-applied
    # ----------------------------
    # If the fixed code is not even valid Python we cannot establish that it is
    # safe, no matter how good the score looks. This is a hard block, not a penalty.
    guardrail_blocks: List[str] = []
    if not _is_valid_python(fixed_code):
        guardrail_blocks.append(
            "Fixed code is not valid Python (syntax check failed); safety cannot be verified."
        )
        score = min(score, GUARDRAIL_SCORE_CAP)
        reasons.extend(guardrail_blocks)

    # ----------------------------
    # Clamp score
    # ----------------------------
    score = max(0, min(100, score))

    # ----------------------------
    # Risk level
    # ----------------------------
    if score >= 75:
        level = "low"
    elif score >= 40:
        level = "medium"
    else:
        level = "high"

    # ----------------------------
    # Auto-fix policy
    # ----------------------------
    should_autofix = level == "low" and not guardrail_blocks

    if not reasons:
        reasons.append("No significant risks detected.")

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "should_autofix": should_autofix,
        "guardrail_blocks": guardrail_blocks,
    }
