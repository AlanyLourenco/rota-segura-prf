from datetime import date

import pytest

from rota_segura.metrics import MetricsEngine


@pytest.fixture
def engine(synthetic_parquet, cfg):
    return MetricsEngine(synthetic_parquet, cfg)


def test_period_uses_last_available_date_not_calendar(engine):
    m = engine.compute()
    assert m.data_max_date == date(2026, 6, 30)
    assert (m.period.start, m.period.end) == (date(2026, 6, 1), date(2026, 6, 30))
    assert (m.previous_period.start, m.previous_period.end) == (date(2026, 5, 2), date(2026, 5, 31))


def test_variation_lethality_severity_brasil(engine):
    m = engine.compute()
    assert m.total_accidents == 90 and m.previous_total == 60
    assert m.variation_pct == 50.0
    assert m.deaths == 3
    assert m.lethality_rate == round(100 * 3 / 90, 2)
    assert m.severity_rate == round(100 * 9 / 90, 2)  # 3 com morte + 6 com ferido grave
    assert m.preliminary is True


def test_uf_filter(engine):
    m = engine.compute("SC")
    assert m.scope == "SC"
    assert m.total_accidents == 60 and m.previous_total == 30
    assert {s.uf for s in m.top_segments} == {"SC"}


def test_rankings(engine):
    m = engine.compute()
    assert len(m.top_causes) == 3
    assert m.top_causes[0].accidents == 30
    top = m.top_segments[0]
    # empate em acidentes (30) → desempate por mortos: BR-101 km 207 (3 mortos)
    assert (top.uf, top.br, top.km, top.deaths) == ("SC", 101, 207, 3)


def test_daily_has_30_points_and_monthly_12_months_window(engine):
    m = engine.compute()
    assert len(m.daily) == 30
    assert m.monthly[0].month >= "2025-07"
    assert m.monthly[-1].month == "2026-06"


def test_numbers_contains_metrics(engine):
    m = engine.compute()
    assert {90.0, 60.0, 50.0, 3.0}.issubset(m.numbers())
    assert {2025.0, 8.0}.issubset(m.numbers())  # ano/mês da série mensal (2025-08)
