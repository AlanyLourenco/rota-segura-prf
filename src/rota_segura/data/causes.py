"""Normalização das grafias de causas, que mudam entre os anos da base PRF.

Duas camadas:
1. `cause_key`: remove acentos/caixa/espaços — variantes só de grafia caem na mesma chave.
2. `_RENAMES`: renomeações conhecidas da taxonomia antiga (até 2020) para a atual.
   Só entram equivalências inequívocas; o resto é mantido como está (sem inventar mapeamentos).
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

_RENAMES: dict[str, str] = {
    "ingestao de alcool": "ingestao de alcool pelo condutor",
    "dormindo": "condutor dormindo",
    "nao guardar distancia de seguranca": "condutor deixou de manter distancia do veiculo da frente",
}

UNKNOWN_CAUSE = "Não informada"


def _spelling_key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def cause_key(text: str) -> str:
    key = _spelling_key(text)
    return _RENAMES.get(key, key)


def normalize_causes(raw: pd.Series) -> pd.Series:
    """Mapeia cada causa para a grafia atual mais frequente entre as variantes da mesma chave.

    Grafias da taxonomia atual (não renomeadas) têm prioridade sobre nomes antigos, mesmo se menos frequentes.
    """
    cleaned = raw.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    cleaned = cleaned.mask(cleaned.isin(["", "NA", "(null)"]), UNKNOWN_CAUSE)
    keys = cleaned.map(cause_key)
    counts = pd.DataFrame({"key": keys, "label": cleaned}).value_counts().reset_index(name="n")
    counts["current"] = counts["label"].map(_spelling_key) == counts["key"]
    canonical = (
        counts.sort_values(["current", "n"], ascending=False, kind="stable")
        .drop_duplicates("key")
        .set_index("key")["label"]
    )
    return keys.map(canonical)
