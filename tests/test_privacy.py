import pandas as pd
import pytest

from rota_segura.data.privacy import (
    SECONDARY_MARK,
    PrivacyViolation,
    assert_llm_safe,
    bin_people,
    suppress_small_cells,
)


def test_allowlist_blocks_unknown_top_level_field():
    with pytest.raises(PrivacyViolation):
        assert_llm_safe({"total_accidents": 1, "linhas_brutas": []})


def test_forbidden_field_nested_is_blocked():
    with pytest.raises(PrivacyViolation):
        assert_llm_safe({"victim_profile": {"faixa": [{"idade": 34, "n": 1}]}})


def test_aggregated_payload_passes():
    assert_llm_safe({"victim_profile": {"sexo": [{"grupo": "Feminino", "n": "<5"}]}, "news": [{"id": 1}]})


def test_bin_people_drops_exact_age_and_witnesses():
    people = pd.DataFrame({
        "data_inversa": ["2026-01-01"] * 4, "uf": ["sc"] * 4, "idade": ["34", "35", "200", "40"],
        "sexo": ["Masculino", "Masculino", "Ignorado", "Feminino"],
        "estado_fisico": ["Óbito", "Óbito", "Ileso", "Ileso"],
        "tipo_envolvido": ["Condutor", "Condutor", "Passageiro", "Testemunha"],
    })  # fmt: skip
    out = bin_people(people)
    assert "idade" not in out.columns
    assert out["n"].sum() == 3  # testemunha excluída
    assert set(out["faixa_etaria"]) == {"30-44", "Não informado"}  # 200 anos é inválido
    assert out.loc[out["faixa_etaria"] == "30-44", "n"].item() == 2


def test_small_cells_are_suppressed():
    rows = suppress_small_cells([{"grupo": "a", "n": 4}, {"grupo": "b", "n": 5}, {"grupo": "c", "n": 3}])
    assert rows == [{"grupo": "a", "n": "<5"}, {"grupo": "b", "n": 5}, {"grupo": "c", "n": "<5"}]


def test_single_suppressed_cell_gets_complementary_suppression():
    rows = [{"estado_fisico": "Óbito", "grupo": "18-29", "n": 40},
            {"estado_fisico": "Óbito", "grupo": "30-44", "n": 12},
            {"estado_fisico": "Óbito", "grupo": "60+", "n": 3}]  # fmt: skip
    out = suppress_small_cells(rows)
    assert [r["n"] for r in out] == [40, SECONDARY_MARK, "<5"]


def test_two_primary_cells_need_no_complement():
    rows = [{"estado_fisico": "Óbito", "grupo": g, "n": n} for g, n in [("a", 40), ("b", 2), ("c", 4)]]
    assert [r["n"] for r in suppress_small_cells(rows)] == [40, "<5", "<5"]


def test_groups_are_independent():
    rows = [{"estado_fisico": "Óbito", "grupo": "a", "n": 9}, {"estado_fisico": "Óbito", "grupo": "b", "n": 1},
            {"estado_fisico": "Lesões Graves", "grupo": "a", "n": 50},
            {"estado_fisico": "Lesões Graves", "grupo": "b", "n": 30}]  # fmt: skip
    assert [r["n"] for r in suppress_small_cells(rows)] == [SECONDARY_MARK, "<5", 50, 30]
