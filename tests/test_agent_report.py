from specflow.harness import build_run_finished, parse_agent_report


def test_parses_last_fenced_json_block() -> None:
    text = """Najpierw myślałem: ```json
{"status": "blocked", "summary": "x", "question": "stare?"}
```
Ostatecznie:
```json
{"status": "done", "summary": "Dodałem serwis logowania.", "notes": "bcrypt w security.py"}
```"""
    report, error = parse_agent_report(text)
    assert error is None and report is not None
    assert report.status == "done"
    assert report.notes == "bcrypt w security.py"


def test_accepts_unfenced_json_at_the_end() -> None:
    report, error = parse_agent_report('Gotowe. {"status": "done", "summary": "ok"}')
    assert error is None and report is not None and report.summary == "ok"


def test_blocked_requires_question() -> None:
    report, error = parse_agent_report('```json\n{"status": "blocked", "summary": "brak"}\n```')
    assert report is None
    assert error is not None and "question" in error


def test_missing_report_is_an_error_not_success() -> None:
    report, error = parse_agent_report("Skończyłem, wszystko działa!")
    assert report is None
    assert error == "Brak raportu końcowego w bloku JSON z polem 'status'."


def test_wrong_status_value_is_reported() -> None:
    report, error = parse_agent_report('```json\n{"status": "finished", "summary": "x"}\n```')
    assert report is None
    assert error is not None and error.startswith("Raport ma zły format")


def test_report_is_parsed_only_for_completed_runs_that_expect_it() -> None:
    final = '```json\n{"status": "done", "summary": "ok"}\n```'
    assert build_run_finished("completed", final, expect_report=True).report is not None
    assert build_run_finished("completed", final, expect_report=False).report is None
    timeout = build_run_finished("timeout", final, expect_report=True, error="limit")
    assert timeout.report is None and timeout.error == "limit"
    missing = build_run_finished("completed", "brak", expect_report=True)
    assert missing.report is None and missing.report_error is not None
