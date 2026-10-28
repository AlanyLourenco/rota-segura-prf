"""Conjunto golden: casos fixos de entrada/saída que os guardrails precisam acertar (R6)."""

import pytest
from pydantic import ValidationError

from rota_segura.evals import GoldenCase, run_suite


def test_golden_suite_all_cases_pass():
    result = run_suite()
    failed = [r.id for r in result.results if not r.ok]
    assert result.ok == result.total, f"casos golden falharam: {failed}"


def test_golden_has_minimum_coverage():
    result = run_suite()
    assert result.total >= 24
    assert {"injecao", "pii", "numero", "causa", "limpo"} <= set(result.by_category)


def test_unknown_expected_rule_rejected():
    with pytest.raises(ValidationError):
        GoldenCase(id="x", kind="input", category="injecao", expect_pass=False, expect_rules=["pi"])


def test_output_case_requires_draft():
    with pytest.raises(ValidationError):
        GoldenCase(id="x", kind="output", category="pii", expect_pass=False)


def test_cli_eval_exit_code(tmp_path, capsys):
    from rota_segura.cli import main

    assert main(["eval"]) == 0
    assert "injecao" in capsys.readouterr().out
    bad = tmp_path / "casos.json"
    bad.write_text('{"cases": [{"id": "x", "kind": "input", "category": "limpo", "uf": "XX", "expect_pass": true}]}',
                   encoding="utf-8")  # fmt: skip
    assert main(["eval", "--cases", str(bad)]) == 1
