"""Guardrails determinísticos de entrada e saída.

Entrada: UF válida, foco opcional curto, sem tentativa de injeção de prompt, dentro do escopo.
Saída: rótulos de fonte, números rastreáveis à base, sem atribuição de causa vinda de notícia, sem PII.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field

from rota_segura.config import VALID_UFS

# --------------------------------------------------------------------------- schema do rascunho do LLM

BASE_SOURCE = "BASE"


class Paragraph(BaseModel):
    text: str = Field(description="Parágrafo em português, sem rótulos; os rótulos vêm de `sources`.")
    sources: list[str] = Field(description='Fontes: "BASE" (dados PRF) e/ou "NEWS:<id>" (notícia).')


class Section(BaseModel):
    title: str
    paragraphs: list[Paragraph]


class Draft(BaseModel):
    """Saída estruturada exigida do LLM redator."""

    headline: str = Field(description="Resumo em uma frase, apenas com dados da BASE.")
    sections: list[Section]


class GuardIssue(BaseModel):
    rule: str
    detail: str
    location: str = ""


class GuardReport(BaseModel):
    passed: bool
    issues: list[GuardIssue] = []


# --------------------------------------------------------------------------- PII

_PII_PATTERNS = {
    "cpf": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "placa": re.compile(r"\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "telefone": re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-\d{4}\b"),
}


def find_pii(text: str) -> list[str]:
    return [name for name, pattern in _PII_PATTERNS.items() if pattern.search(text)]


def redact_pii(text: str) -> str:
    for name, pattern in _PII_PATTERNS.items():
        text = pattern.sub(f"[{name.upper()} REMOVIDO]", text)
    return text


# --------------------------------------------------------------------------- entrada

_INJECTION = re.compile(
    r"(ignore|desconsidere|esque[cç]a|forget|disregard).{0,40}(instru|regras|rules|anterior|previous|prompt)|"
    r"system prompt|"
    r"you are now|voc[eê] agora [eé]|jailbreak|<\s*/?\s*(system|instructions?)\s*>",
    re.I,
)
_IN_SCOPE = re.compile(
    r"acident|rodovi|tr[aâ]nsito|seguran|PRF|BR-?\d|feriado|obra|causa|trecho|letalidade|gravidade|v[ií]tima",
    re.I,
)
MAX_FOCUS_CHARS = 200


class InputRejected(ValueError):
    pass


def validate_request(uf: str | None, focus: str | None) -> tuple[str | None, str | None]:
    """Normaliza e valida a requisição; levanta `InputRejected` antes de qualquer chamada ao LLM."""
    if uf:
        uf = uf.strip().upper()
        if uf in {"BR", "BRASIL"}:
            uf = None
        elif uf not in VALID_UFS:
            raise InputRejected(f"UF inválida: {uf!r}. Use uma sigla como SC, SP ou omita para Brasil.")
    if focus:
        focus = focus.strip()
        if len(focus) > MAX_FOCUS_CHARS:
            raise InputRejected(f"Foco excede {MAX_FOCUS_CHARS} caracteres.")
        if _INJECTION.search(focus):
            raise InputRejected("Foco contém instruções que tentam alterar o comportamento do agente.")
        if not _IN_SCOPE.search(focus):
            raise InputRejected("Foco fora do escopo (segurança nas rodovias federais).")
        if find_pii(focus):
            raise InputRejected("Foco contém dado pessoal; remova antes de enviar.")
    return uf, focus or None


# --------------------------------------------------------------------------- saída

_NUMBER = re.compile(r"(?<![\w\-.,])(?:-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?)")
_CAUSAL = re.compile(
    r"\b(causad[oa]s?|caus[ao]u?|devido a|por causa d|em raz[aã]o d|provocad[oa]s?|motivad[oa]s?|"
    r"culpa|respons[aá]ve(?:l|is) pel[oa]s?)\b",
    re.I,
)
_NUMBER_TOLERANCE = 0.051  # aceita arredondamento de 1 casa (9,56 -> 9,6)
_REPORT_CONSTANTS = {0.0, 5.0, 12.0, 30.0, 100.0}  # top 5, 12 meses, 30 dias, por 100 acidentes


def _parse_number(token: str) -> float:
    if "," in token:  # formato pt-BR: 1.234,5
        return float(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", token):  # 6.149 (milhar)
        return float(token.replace(".", ""))
    return float(token)


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def numbers_in(text: str) -> set[float]:
    """Números citados num texto (ex.: título + snippet de notícia), no mesmo parser do guardrail."""
    return {_parse_number(token) for token in _NUMBER.findall(text)}


def untraceable_numbers(text: str, allowed: set[float]) -> list[str]:
    """Números do texto que não correspondem a nenhuma métrica calculada."""
    bad = []
    for token in _NUMBER.findall(text):
        value = _parse_number(token)
        if value in _REPORT_CONSTANTS:
            continue
        if not any(abs(value - a) <= _NUMBER_TOLERANCE for a in allowed):
            bad.append(token)
    return bad


def validate_draft(
    draft: Draft, allowed_numbers: set[float], news_ids: set[int], news_numbers: dict[int, set[float]] | None = None
) -> GuardReport:
    """Valida o rascunho. Números só podem vir das métricas (fonte BASE) ou das notícias citadas no parágrafo."""
    news_numbers = news_numbers or {}
    issues: list[GuardIssue] = []
    if find_pii(draft.headline):
        issues.append(GuardIssue(rule="pii", detail="PII no headline", location="headline"))
    for bad in untraceable_numbers(draft.headline, allowed_numbers):
        issues.append(GuardIssue(rule="numero_nao_rastreavel", detail=bad, location="headline"))

    for s_idx, section in enumerate(draft.sections):
        for p_idx, par in enumerate(section.paragraphs):
            loc = f"sections[{s_idx}].paragraphs[{p_idx}]"
            issues.extend(_check_paragraph(par, loc, allowed_numbers, news_ids, news_numbers))
    return GuardReport(passed=not issues, issues=issues)


def _check_paragraph(
    par: Paragraph, loc: str, allowed: set[float], news_ids: set[int], news_numbers: dict[int, set[float]]
) -> list[GuardIssue]:
    issues: list[GuardIssue] = []
    if not par.sources:
        return [GuardIssue(rule="sem_fonte", detail="Parágrafo sem fonte rotulada", location=loc)]

    cited_news = set()
    for src in par.sources:
        if src == BASE_SOURCE:
            continue
        match = re.fullmatch(r"NEWS:(\d+)", src)
        if not match or int(match.group(1)) not in news_ids:
            issues.append(GuardIssue(rule="fonte_invalida", detail=src, location=loc))
        else:
            cited_news.add(int(match.group(1)))

    if found := find_pii(par.text):
        issues.append(GuardIssue(rule="pii", detail=", ".join(found), location=loc))

    traceable = set(allowed) if BASE_SOURCE in par.sources else set()
    traceable |= set().union(*(news_numbers.get(i, set()) for i in cited_news))
    for bad in untraceable_numbers(par.text, traceable):
        issues.append(GuardIssue(rule="numero_nao_rastreavel", detail=bad, location=loc))

    # Atribuição causal só pode vir da base. Notícia (sozinha ou misturada à base) + verbo causal = bloqueio.
    if cited_news and _CAUSAL.search(_strip_accents(par.text)) is not None:
        issues.append(GuardIssue(
            rule="causa_de_noticia",
            detail="Atribuição causal em parágrafo baseado em notícia; causas só podem vir da base PRF.",
            location=loc,
        ))  # fmt: skip
    return issues
