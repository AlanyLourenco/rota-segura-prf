import io
from datetime import date

import pandas as pd

from rota_segura.data.causes import UNKNOWN_CAUSE, normalize_causes
from rota_segura.data.ingest import clean_occurrences, read_raw_csv

HEADER = (
    '"id";"data_inversa";"dia_semana";"horario";"uf";"br";"km";"municipio";"causa_acidente";'
    '"tipo_acidente";"classificacao_acidente";"fase_dia";"sentido_via";"condicao_metereologica";'
    '"tipo_pista";"tracado_via";"uso_solo";"pessoas";"mortos";"feridos_leves";"feridos_graves";"ilesos";'
    '"ignorados";"feridos";"veiculos";"latitude";"longitude";"regional";"delegacia";"uop"'
)
ROW = (
    '652519;2025-01-01;"quarta-feira";"07:50:00";"ce";116;546,2;"PENAFORTE";"Pista esburacada";'
    '"Colisão frontal";NA;"Pleno dia";"Crescente";"Céu Claro";"Simples";"Reta";"Não";6;1;1;0;1;4;1;6;'
    '-7,812288;-39,08333306;"SPRF-CE";"DEL05-CE";"UOP03-DEL05-CE"'
)


def _raw() -> pd.DataFrame:
    return read_raw_csv(io.BytesIO(f"{HEADER}\n{ROW}\n".encode("latin-1")))


def test_reads_latin1_and_semicolon():
    df = _raw()
    assert df.loc[0, "tipo_acidente"] == "Colisão frontal"
    assert df.loc[0, "km"] == "546,2"


def test_clean_converts_decimal_comma_and_flags_preliminary():
    out = clean_occurrences(_raw(), today=date(2025, 2, 1))
    row = out.iloc[0]
    assert row["km"] == 546.2
    assert row["latitude"] == -7.812288
    assert row["uf"] == "CE"
    assert row["mortos"] == 1
    assert row["classificacao_acidente"] is None
    assert bool(row["preliminar"]) is True
    assert "id" not in out.columns  # identificador do acidente é descartado


def test_previous_year_consolidated_after_march_revision():
    out = clean_occurrences(_raw(), today=date(2026, 4, 10))
    assert bool(out.iloc[0]["preliminar"]) is False


def test_causes_unify_spelling_variants_and_renames():
    raw = pd.Series(
        [
            "Velocidade Incompatível",
            "Velocidade incompativel",
            "velocidade  incompatível",
            "Ingestão de Álcool",
            "Ingestão de álcool pelo condutor",
            "NA",
        ]
    )
    out = normalize_causes(raw).tolist()
    assert out[0] == out[1] == out[2] == "Velocidade Incompatível"
    assert out[3] == out[4] == "Ingestão de álcool pelo condutor"
    assert out[5] == UNKNOWN_CAUSE
