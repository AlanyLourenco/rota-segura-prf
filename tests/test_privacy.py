import pandas as pd
import pytest

from rota_segura.data.privacy import PrivacyViolation, assert_llm_safe, bin_people, suppress_small_cells


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
    rows = suppress_small_cells([{"grupo": "a", "n": 4}, {"grupo": "b", "n": 5}], min_cell_size=5)
    assert rows == [{"grupo": "a", "n": "<5"}, {"grupo": "b", "n": 5}]
