"""Política de dados sensíveis (LGPD).

Princípios:
- Minimização na origem: a base "por pessoa" é agregada já na ingestão (`bin_people`); linhas
  individuais (idade exata, sexo + local + data, marca do veículo...) nunca são gravadas em `processed/`.
- Allowlist: só as chaves em `LLM_ALLOWED_FIELDS` podem compor o contexto enviado ao LLM.
- Supressão: em recortes de pessoas, células com n < `min_cell_size` viram "<5" (evita reidentificação
  em recortes pequenos, ex.: "uma mulher de 60+ anos morta na BR-xxx no dia tal").
- Supressão complementar: se um grupo (ex.: óbitos) tem uma única célula "<5", a menor célula visível
  também é ocultada, pois o total do grupo é público (`deaths`) e a célula seria deduzível por subtração.
  Grupo só com células pequenas é omitido inteiro (ex.: 3 óbitos, todos homens 60+, numa UF pequena).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

LLM_ALLOWED_FIELDS = frozenset({
    "uf", "scope", "period", "previous_period", "total_accidents", "previous_total", "variation_pct",
    "lethality_rate", "severity_rate", "deaths", "severe_injuries", "top_causes", "top_segments",
    "daily", "monthly", "preliminary", "data_max_date", "victim_profile", "news",
})  # fmt: skip

FORBIDDEN_FIELDS = frozenset({
    "pesid", "id_veiculo", "id_acidente", "idade", "latitude", "longitude", "marca", "ano_fabricacao_veiculo",
    "nome", "cpf", "placa", "horario", "municipio",
})  # fmt: skip

AGE_BINS = [0, 18, 30, 45, 60, 111]
AGE_LABELS = ["0-17", "18-29", "30-44", "45-59", "60+"]
NOT_INFORMED = "Não informado"
SECONDARY_MARK = "suprimido"


class PrivacyViolation(ValueError):
    pass


def assert_llm_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Garante que o contexto do LLM só tem campos permitidos e nenhum campo sensível em qualquer nível."""
    unexpected = set(payload) - LLM_ALLOWED_FIELDS
    if unexpected:
        raise PrivacyViolation(f"Campos não permitidos ao LLM: {sorted(unexpected)}")
    leaked = _find_keys(payload) & FORBIDDEN_FIELDS
    if leaked:
        raise PrivacyViolation(f"Campos sensíveis no contexto do LLM: {sorted(leaked)}")
    return payload


def _find_keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj).union(*(_find_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_find_keys(v) for v in obj))
    return set()


def bin_people(people: pd.DataFrame) -> pd.DataFrame:
    """Converte a base "por pessoa" em contagens por dia × UF × faixa etária × sexo × estado físico × envolvido.

    Testemunhas são excluídas (não são vítimas nem envolvidos diretos).
    """
    people = people[people["tipo_envolvido"] != "Testemunha"]
    ages = pd.to_numeric(people["idade"], errors="coerce")
    ages = ages.where((ages >= 0) & (ages <= 110))  # idades impossíveis viram "Não informado"
    unknown = {"": NOT_INFORMED, "NA": NOT_INFORMED, "Ignorado": NOT_INFORMED, "Não Informado": NOT_INFORMED}
    frame = pd.DataFrame({
        "data": pd.to_datetime(people["data_inversa"], errors="coerce"),
        "uf": people["uf"].str.strip().str.upper(),
        "faixa_etaria": pd.cut(ages, AGE_BINS, labels=AGE_LABELS, right=False).astype(str)
        .replace("nan", NOT_INFORMED),
        "sexo": people["sexo"].replace(unknown),
        "estado_fisico": people["estado_fisico"].replace(unknown),
        "tipo_envolvido": people["tipo_envolvido"].replace(unknown),
    })  # fmt: skip
    return frame.dropna(subset=["data"]).value_counts().reset_index(name="n")


def suppress_small_cells(
    rows: list[dict[str, Any]], min_cell_size: int = 5, group_key: str | None = "estado_fisico"
) -> list[dict[str, Any]]:
    """Substitui contagens < `min_cell_size` por "<min" e aplica supressão complementar por grupo."""
    out = [{**row, "n": row["n"] if row["n"] >= min_cell_size else f"<{min_cell_size}"} for row in rows]
    groups: dict[Any, list[int]] = {}
    for idx, row in enumerate(rows):
        groups.setdefault(row.get(group_key) if group_key else None, []).append(idx)
    dropped: set[int] = set()
    for idxs in groups.values():
        primary = [i for i in idxs if rows[i]["n"] < min_cell_size]
        visible = [i for i in idxs if rows[i]["n"] >= min_cell_size]
        if primary and not visible:  # só células pequenas: com o total público, o grupo inteiro seria revelado
            dropped.update(idxs)
        elif len(primary) == 1:
            out[min(visible, key=lambda i: rows[i]["n"])]["n"] = SECONDARY_MARK
    return [row for idx, row in enumerate(out) if idx not in dropped]
