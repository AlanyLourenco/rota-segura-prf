"""Fixtures com uma base sintética pequena (não depende de rede nem dos CSVs reais)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pandas as pd
import pytest

from rota_segura.config import Settings


def _occurrence(day: date, uf: str, br: int, km: float, cause: str, mortos=0, graves=0) -> dict:
    return {
        "data": pd.Timestamp(day),
        "uf": uf,
        "br": br,
        "km": km,
        "municipio": "X",
        "causa_acidente": cause,
        "tipo_acidente": "Colisão",
        "classificacao_acidente": "Com Vítimas Feridas",
        "fase_dia": "Pleno dia",
        "condicao_metereologica": "Céu Claro",
        "pessoas": 2,
        "mortos": mortos,
        "feridos_leves": 1,
        "feridos_graves": graves,
        "ilesos": 1,
        "feridos": 1 + graves,
        "veiculos": 2,
        "latitude": -27.5,
        "longitude": -48.6,
        "preliminar": day.year == 2026,
    }


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return replace(
        Settings(),
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        reports_dir=tmp_path / "reports",
        audit_dir=tmp_path / "audit",
    )


@pytest.fixture
def synthetic_parquet(cfg: Settings):
    """Período atual (01–30/06/2026): SC 40 acidentes, SP 20. Período anterior: SC 20, SP 20."""
    end = date(2026, 6, 30)
    rows = []
    for i in range(30):
        day = end - timedelta(days=i)
        rows += [_occurrence(day, "SC", 101, 207.4, "Velocidade Incompatível", mortos=1 if i < 3 else 0)]
        rows += [_occurrence(day, "SC", 282, 10.0, "Ingestão de álcool pelo condutor", graves=1 if i < 6 else 0)]
        rows += [_occurrence(day, "SP", 116, 230.0, "Reação tardia ou ineficiente do condutor")]
        prev = day - timedelta(days=30)
        rows += [_occurrence(prev, "SC", 101, 50.0, "Velocidade Incompatível")]
        rows += [_occurrence(prev, "SP", 116, 230.0, "Reação tardia ou ineficiente do condutor")]
    rows += [_occurrence(date(2025, 8, 15), "SC", 101, 1.0, "Velocidade Incompatível")]
    cfg.processed_dir.mkdir(parents=True)
    df = pd.DataFrame(rows)
    df["br"] = df["br"].astype("Int64")
    df.to_parquet(cfg.occurrences_parquet, index=False)
    return cfg.occurrences_parquet
