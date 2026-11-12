# BugHound Model Card

Everything below is based on what was actually implemented and run in this repository. **No live Gemini call was made** (no `GEMINI_API_KEY` was available), so every Gemini-path statement is based on code reading and mocked/scripted clients, and is labelled as such.

---

## A. System overview

**Name:** BugHound
**Purpose:** Analyze a Python snippet, propose a fix, run reliability checks, and decide whether the fix is safe enough to apply automatically.
**Intended users:** Students learning agentic workflows and AI reliability. It is a teaching tool, not a production code-review product.
**Main capabilities:**
- Detect a small set of issues (print statements, bare `except:`, TODO comments) with heuristics, or any issue an LLM reports.
- Propose a rewritten file (heuristic regex fixes or an LLM rewrite).
- Score the risk of the rewrite and decide `should_autofix`.
- Show a diff, the risk report and a step-by-step agent trace in a Streamlit UI.

## B. Agent workflow

`PLAN → ANALYZE → ACT → TEST → REFLECT` (`BugHoundAgent.run` in `bughound_agent.py`)

| Step | What happens | Heuristics vs Gemini |
|---|---|---|
| PLAN | Logs the plan. | Neither. |
| ANALYZE | Finds issues. | Gemini if a client is provided, otherwise heuristics. LLM output is strictly validated; on any failure the agent logs the reason and falls back to heuristics. |
| ACT | Proposes fixed code. | Gemini rewrite if a client exists, otherwise regex rewrites. Empty output or an API error falls back to the heuristic fixer. |
| TEST | `assess_risk` scores the fix (0-100) and may hard-block it. | Always deterministic local code; never an LLM. |
| REFLECT | Logs whether the fix may be auto-applied. | Driven by `should_autofix`. |

## C. Inputs and outputs

- **Input:** one Python source string (pasted or one of `sample_code/*.py`).
- **Outputs:** `issues` (list of `{type, severity, msg}`), `fixed_code`, a diff (built in the UI), `risk` (`score`, `level`, `reasons`, `should_autofix`, `guardrail_blocks`), and `logs` (the agent trace).

## D. Reliability rules (`reliability/risk_assessor.py`)

1. **Removed `return` statements.** Checks if `"return"` appears in the original but not the fixed code (-30). *Why:* a rewrite that drops returns silently changes behavior.
   *False positive:* the word "return" only appeared in a comment/string and was legitimately deleted. *False negative:* one of several `return`s is removed but others remain, so the substring check still passes.
2. **Fixed code much shorter than original.** Fewer than 50% of the lines (-20). *Why:* big shrinkage suggests the model deleted logic or replied with a stub (observed with MockClient, whose "fix" is a one-line comment). *False positive:* a legitimate cleanup that deletes dead code. *False negative:* logic replaced by equally long but wrong code.
3. **Severity deductions** (High -40, Medium -20, Low -5 per issue). *Why:* files with serious issues need more scrutiny. *False positive:* a High issue that the fix resolves cleanly still lowers the score. *False negative:* the LLM mislabels a serious issue as Low.

(New rules are described in section H.)

## E. Failure modes (observed by running the code)

1. **Silent auto-apply of a changed function signature.** Before the Part 3 change, `def f(x)` → `def f(x, y)` scored 100 / low / auto-fix YES, because no rule looked at signatures. A caller `f(1)` would break.
2. **Auto-apply of a syntactically broken fix.** Before the Part 4 guardrail, a scripted LLM fixer returning `def f():\n    return 1 +` scored 95 / low / auto-fix YES. Invalid Python input (`def f(:`) was also rated 95 / low.
3. **Garbage analyzer output accepted.** Before Part 2, `[{"type":"Reliability","severity":"Catastrophic","msg":""}]` was accepted as a real issue (empty message, invalid severity).
4. **Misleading trace in "Heuristic only" mode (found and fixed).** In the live app, `mixed_issues.py` in Heuristic mode showed "Using LLM analyzer", then "LLM output was not parseable JSON. Falling back to heuristics", then risk HIGH, score 0, auto-fix NO. The cause: the app passed `MockClient` in this mode, so the agent logged an LLM step although no AI ran, and the MockClient "fix" was a one-line comment, which tripped the shorter-code, return-removed and bare-except rules. Fix: Heuristic mode now passes no client; the trace says "Using heuristic analyzer (offline mode)", the real heuristic fix is used, and the result is 30 / HIGH / NO (a headless Streamlit run confirmed this). `MockClient` remains only in tests, to simulate a model that returns non-JSON.
5. **Still-open miss:** heuristics only find three patterns, so e.g. `x / y` without a zero check is never reported in offline mode.

## F. Heuristic vs Gemini

- **Heuristics:** deterministic, offline, consistent on the three patterns (all four sample files gave stable results). Weak: tiny coverage, substring matching (`"print("` also matches inside strings/comments), regex rewrite of `except:`.
- **Gemini (not live-tested):** the prompts ask it to find broader problems and rewrite the file. Expected strengths: broader coverage and context-aware fixes. Expected weaknesses: hallucinated issues, format drift, over-eager rewrites, needs network/API key/quota.
- **Fallback behavior (verified with mocked clients):** invalid/empty/mis-typed analyzer JSON, or an exception from the client, falls back to heuristics with the reason in the trace. `GeminiClient.complete` itself returns `""` on any API error, which is also treated as invalid output.
- **The app reports the engine honestly:** results carry `analysis_source` / `fix_source` (`llm` or `heuristic`); in Gemini mode the UI warns when results actually came from heuristics.
- **Risk scorer vs intuition (offline comparison, before → after the changes; scored with the agent given `MockClient`, so the fix text differs from what the app now produces in Heuristic mode):** sample files `cleanish` (100/low), `mixed_issues` (30/high heuristic), `flaky_try_except` (55/medium), `print_spam` (95/low) were unchanged; only the unsafe cases above changed.
- **Verification status: PENDING.** No Gemini call has been made on any sample file. `GeminiClient` is only unit-tested with the SDK mocked (API error returns `""`; temperature is passed to the SDK config).
- **What needs a real key:** whether Gemini finds more than heuristics on the sample files, the quality of its fixes, and how often it returns invalid JSON.

## G. Human-in-the-loop

**Scenario:** the proposed fix is not valid Python (or changes a function signature, removes returns, or shrinks the file).
- **Trigger:** `ast.parse(fixed_code)` fails (hard block), or the score is below 75.
- **Where implemented:** `assess_risk` in `reliability/risk_assessor.py` (decision), with the agent logging `TEST: GUARDRAIL: ...` in `bughound_agent.py`.
- **What the user sees:** Auto-fix? NO, risk level HIGH, the reason "Fixed code is not valid Python (syntax check failed); safety cannot be verified." in the risk report, and "Human review recommended" in the trace.
- **Why:** a human must decide because no automated check here can prove the rewrite preserves behavior.

## H. Improvements made

### 1. Strict structured-output validation (Part 2, analyzer)
- **Problem:** `_normalize_issues` coerced anything into an issue (`str(...)` defaults, skipped non-dicts), so malformed model output looked valid.
- **Design:** reject the whole response if any item is invalid; fall back to heuristics and record the reason.
- **Implementation:** `_parse_and_validate_issues` / `_validate_issues` in `bughound_agent.py`. Requires string `type`, `severity` in Low/Medium/High (case-normalized), `msg` of at least 5 characters. A valid `[]` is accepted as "no issues".
- **Tests:** `tests/test_analyzer_validation.py` (valid, empty array, embedded JSON, invalid JSON, empty, missing fields, wrong types, bad severity, empty msg, mixed good+bad, client exception).
- **Benefit:** garbage never reaches the fixer or the UI, and the trace says why the AI output was rejected.

### 2. Function-signature risk signal (Part 3, risk)
- **Problem:** changed or deleted function signatures scored 100 / auto-fix YES.
- **Design:** one -30 penalty (score 70 → medium → no auto-fix). Skipped when the "much shorter" rule already fired, to avoid double-penalizing one destructive rewrite. Whitespace-only changes are ignored.
- **Implementation:** `_function_signatures` and a rule in `assess_risk`.
- **Tests:** `tests/test_risk_assessor.py` (safe fix stays low, signature change, whitespace, removed function, no double penalty, removed return, threshold/decision consistency, existing bare-except math).
- **Benefit:** callers breaking silently is now caught. Limit: only single-line `def` headers are compared.

### 3. Syntax-validity guardrail (Part 4)
- **Problem:** a broken fix (or broken input) could score "low" and be auto-applied.
- **Design:** a hard block rather than a penalty: score is capped at 39 (high) and `should_autofix` is forced False, so the score and decision remain consistent.
- **Implementation:** `_is_valid_python` + `guardrail_blocks` in `assess_risk`; the agent logs each block as `TEST: GUARDRAIL: ...`.
- **Tests:** `test_regression_syntax_broken_llm_fix_is_never_autoapplied` (verified to FAIL when the syntax check is stubbed out and pass with it), plus invalid-input, empty-file, comments-only, prose-fixer, and sample-file tests.
- **Benefit:** output that cannot be parsed is never auto-applied.

## I. Limitations

- Valid syntax does not mean correct behavior; the checks are structural and substring-based, not semantic. Behavior-changing fixes can still look "low risk".
- Heuristic analysis covers only three patterns and has false positives (`print(` in strings) and false negatives.
- LLMs can hallucinate issues or fixes; validation checks the *shape* of the output, not its truth.
- Gemini mode depends on an API key, network and quota, and was **not exercised live** here.
- Tests are offline and use scripted clients; they cannot measure real-model behavior.
- Empty input is reported as "no fix produced" (high risk), which is conservative rather than informative.
- This is a learning project; it is not evidence of production readiness, and a human should review every fix.
