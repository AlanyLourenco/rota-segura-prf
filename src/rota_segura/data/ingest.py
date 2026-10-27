"""Download e normalização da base de acidentes da PRF (agrupada por ocorrência)."""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

from rota_segura.config import DRIVE_DOWNLOAD_URL, PRF_OCCURRENCE_FILES, PRF_PEOPLE_FILES, Settings, settings
from rota_segura.data.causes import normalize_causes
from rota_segura.data.privacy import bin_people

log = logging.getLogger(__name__)

# Colunas usadas. Ficam de fora: id (identificador) e regional/delegacia/uop (operacional).
# lat/long são tratadas e guardadas, mas `privacy.LLM_ALLOWED_FIELDS` impede que cheguem ao LLM.
OCCURRENCE_COLUMNS = [
    "data_inversa", "uf", "br", "km", "municipio", "causa_acidente", "tipo_acidente",
    "classificacao_acidente", "fase_dia", "condicao_metereologica", "pessoas", "mortos",
    "feridos_leves", "feridos_graves", "ilesos", "feridos", "veiculos", "latitude", "longitude",
]  # fmt: skip


def download_year(year: int, file_id: str, raw_dir: Path, prefix: str = "datatran", force: bool = False) -> Path:
    """Baixa o ZIP do ano para `raw_dir`; reusa o cache se já existir."""
    target = raw_dir / f"{prefix}{year}.zip"
    if target.exists() and not force:
        return target
    raw_dir.mkdir(parents=True, exist_ok=True)
    url = DRIVE_DOWNLOAD_URL.format(file_id=file_id)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(url)
        response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError(f"Download de {year} não retornou um ZIP (Drive pode ter bloqueado).")
    target.write_bytes(response.content)
    return target


def read_raw_csv(source: Path | io.BytesIO) -> pd.DataFrame:
    """Lê um CSV (ou ZIP com um CSV) no formato da PRF: latin-1, separador `;`."""
    if isinstance(source, Path) and source.suffix == ".zip":
        with zipfile.ZipFile(source) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            source = io.BytesIO(zf.read(name))
    return pd.read_csv(source, sep=";", encoding="latin-1", dtype=str, keep_default_na=False)


def _to_number(series: pd.Series) -> pd.Series:
    """'546,2' -> 546.2 ; '-23,48' -> -23.48 ; 'NA'/'' -> NaN."""
    return pd.to_numeric(series.str.strip().str.replace(",", ".", regex=False), errors="coerce")


def clean_occurrences(df: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """Aplica os tratamentos da base: tipos, km numérico, causas canônicas, flag preliminar."""
    today = today or date.today()
    out = df[OCCURRENCE_COLUMNS].copy()
    out["data"] = pd.to_datetime(out.pop("data_inversa"), errors="coerce", dayfirst=False)
    out = out.dropna(subset=["data"])
    out["uf"] = out["uf"].str.strip().str.upper()
    out["br"] = pd.to_numeric(out["br"], errors="coerce").astype("Int64")
    for col in ["km", "latitude", "longitude"]:
        out[col] = _to_number(out[col])
    for col in ["pessoas", "mortos", "feridos_leves", "feridos_graves", "ilesos", "feridos", "veiculos"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["causa_acidente"] = normalize_causes(out["causa_acidente"])
    for col in ["tipo_acidente", "classificacao_acidente", "municipio", "fase_dia", "condicao_metereologica"]:
        out[col] = out[col].replace({"NA": None, "": None}).str.strip()
    out["preliminar"] = out["data"].dt.year.map(lambda y: _is_preliminary(y, today))
    return out.reset_index(drop=True)


def _is_preliminary(year: int, today: date) -> bool:
    """Ano corrente é preliminar; ano anterior só fica consolidado após a revisão de março."""
    return year >= today.year or (year == today.year - 1 and today.month < 4)


def _load_years(files: dict[int, str], prefix: str, years: list[int], cfg: Settings, force: bool) -> pd.DataFrame:
    frames = []
    for year in years:
        cached = cfg.raw_dir / f"{prefix}{year}.zip"
        try:
            path = download_year(year, files[year], cfg.raw_dir, prefix=prefix, force=force)
        except Exception as exc:  # cache é a rede de segurança (R1.6)
            if not cached.exists():
                log.warning("%s%s ignorado: %s", prefix, year, exc)
                continue
            log.warning("Falha no download de %s%s (%s); usando cache.", prefix, year, exc)
            path = cached
        frames.append(read_raw_csv(path))
    if not frames:
        raise RuntimeError(f"Nenhum arquivo '{prefix}' da PRF disponível.")
    return pd.concat(frames, ignore_index=True)


def ingest(years: list[int] | None = None, cfg: Settings = settings, force: bool = False) -> dict[str, Path]:
    """Baixa, limpa e grava os Parquets de ocorrências e de pessoas (já agregado). Retorna os caminhos."""
    years = years or sorted(PRF_OCCURRENCE_FILES)
    cfg.processed_dir.mkdir(parents=True, exist_ok=True)

    occurrences = clean_occurrences(_load_years(PRF_OCCURRENCE_FILES, "datatran", years, cfg, force))
    occurrences.to_parquet(cfg.occurrences_parquet, index=False)
    outputs = {"acidentes": cfg.occurrences_parquet}

    try:
        people = _load_years(PRF_PEOPLE_FILES, "pessoa", years, cfg, force)
    except RuntimeError as exc:
        log.warning("Base por pessoa indisponível: %s", exc)
        return outputs
    bin_people(people).to_parquet(cfg.people_parquet, index=False)  # LGPD: só agregado em disco
    outputs["pessoas_agregado"] = cfg.people_parquet
    return outputs


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
