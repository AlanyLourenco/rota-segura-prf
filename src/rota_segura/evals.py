"""Avaliação dos guardrails com um conjunto golden (casos fixos com resultado esperado).

Cada caso descreve uma entrada do usuário (`kind="input"`) ou um rascunho do LLM (`kind="output"`) e o que
o guardrail deve decidir. Rodado no pytest e via `rota-segura eval`; os dados são sintéticos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

from rota_segura.config import ROOT
from rota_segura.guardrails import Draft, InputRejected, numbers_in, validate_draft, validate_request

DEFAULT_CASES = ROOT / "evals" / "golden_guardrails.json"
KNOWN_RULES = frozenset({"pii", "numero_nao_rastreavel", "sem_fonte", "fonte_invalida", "causa_de_noticia"})


class GoldenCase(BaseModel):
    id: str
    kind: Literal["input", "output"]
    category: str
    uf: str | None = None
    focus: str | None = None
    draft: Draft | None = None
    allowed_numbers: list[float] = []
    news: dict[int, str] = {}  # id -> título + snippet
    expect_pass: bool
    expect_rules: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> GoldenCase:
        if unknown := set(self.expect_rules) - KNOWN_RULES:
            raise ValueError(f"Regras desconhecidas: {sorted(unknown)}")
        if self.kind == "output" and self.draft is None:
            raise ValueError("Caso de saída exige `draft`.")
        return self


class CaseResult(BaseModel):
    id: str
    category: str
    ok: bool
    got_rules: list[str] = []


class SuiteResult(BaseModel):
    total: int
    ok: int
    results: list[CaseResult]
    by_category: dict[str, tuple[int, int]]  # categoria -> (ok, total)


def load_cases(path: Path = DEFAULT_CASES) -> list[GoldenCase]:
    return [GoldenCase.model_validate(c) for c in json.loads(path.read_text(encoding="utf-8"))["cases"]]


def run_case(case: GoldenCase) -> CaseResult:
    if case.kind == "input":
        try:
            validate_request(case.uf, case.focus)
            passed, rules = True, []
        except InputRejected:
            passed, rules = False, []
    else:
        report = validate_draft(
            case.draft, set(case.allowed_numbers), set(case.news),
            news_numbers={i: numbers_in(text) for i, text in case.news.items()},
        )  # fmt: skip
        passed, rules = report.passed, sorted({i.rule for i in report.issues})
    ok = passed == case.expect_pass and set(case.expect_rules) <= set(rules)
    return CaseResult(id=case.id, category=case.category, ok=ok, got_rules=rules)


def run_suite(path: Path = DEFAULT_CASES) -> SuiteResult:
    results = [run_case(c) for c in load_cases(path)]
    by_category: dict[str, tuple[int, int]] = {}
    for r in results:
        ok, total = by_category.get(r.category, (0, 0))
        by_category[r.category] = (ok + r.ok, total + 1)
    return SuiteResult(total=len(results), ok=sum(r.ok for r in results), results=results, by_category=by_category)
