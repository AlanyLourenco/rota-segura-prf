"""Configuração central: caminhos, fontes de dados e parâmetros do relatório."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]

# IDs dos arquivos no Google Drive publicados em
# https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf
PRF_OCCURRENCE_FILES: dict[int, str] = {
    2024: "14lB0vqMFkaZj8HZ44b0njYgxs9nAN8KO",
    2025: "1-G3MdmHBt6CprDwcW99xxC4BZ2DU5ryR",
    2026: "1A3IirNm0AzRaSosA1IS94DOVmvKsn0Ol",
}
PRF_PEOPLE_FILES: dict[int, str] = {
    2024: "14lVfqdoE2gxDliaKZu7K9Mx6847maPtl",
    2025: "1-Gp9S-ALO0D1nT8S_OKoC8xlW7BY8F82",
    2026: "1B_rvx1kPHuFowP5rs84ZO-57gN8yUs85",
}
DRIVE_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"

VALID_UFS = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
})  # fmt: skip


@dataclass(frozen=True)
class Settings:
    raw_dir: Path = ROOT / "data" / "raw"
    processed_dir: Path = ROOT / "data" / "processed"
    reports_dir: Path = ROOT / "reports"
    audit_dir: Path = ROOT / "audit"
    period_days: int = 30
    monthly_window: int = 12
    top_n: int = 5
    min_cell_size: int = 5  # supressão LGPD para agregados por pessoa
    max_writer_attempts: int = 3
    max_news: int = 8
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "google_genai:gemini-3.6-flash"))
    tavily_api_key: str | None = field(default_factory=lambda: os.getenv("TAVILY_API_KEY"))

    @property
    def occurrences_parquet(self) -> Path:
        return self.processed_dir / "acidentes.parquet"

    @property
    def people_parquet(self) -> Path:
        return self.processed_dir / "pessoas_agregado.parquet"


settings = Settings()
