"""Relatório HTML didático: autossuficiente, sem script, com escape de conteúdo vindo da internet."""

import json

from rota_segura.metrics import MetricsEngine
from rota_segura.service import run_report


def _run_with_news(cfg, synthetic_parquet, tmp_path, news: list[dict]):
    snapshot = tmp_path / "noticias.json"
    snapshot.write_text(json.dumps({"items": news}), encoding="utf-8")
    result = run_report(
        cfg, uf="SC", offline=True, news_from=snapshot, engine=MetricsEngine(synthetic_parquet, cfg)
    )  # fmt: skip
    assert result.status == "ok", result.reason
    return (result.report_path.parent / "relatorio.html").read_text(encoding="utf-8")


def test_html_report_is_self_contained_and_didactic(cfg, synthetic_parquet, tmp_path):
    html = _run_with_news(cfg, synthetic_parquet, tmp_path, [])
    assert "<script" not in html.lower()
    assert 'src="data:image/png;base64,' in html and 'src="acidentes' not in html  # gráficos embutidos
    for text in ("Acidentes", "Letalidade", "Gravidade", "Por que e onde acontecem", "Como ler"):
        assert text in html
    assert "SC · BR-101 · km 207" in html  # trecho crítico na tabela do gráfico


def test_html_report_escapes_news_and_blocks_non_http_links(cfg, synthetic_parquet, tmp_path):
    evil = {
        "id": 1, "title": '<img src=x onerror="alert(1)">Acidente na BR-101', "source": "<b>Fonte</b>",
        "url": "javascript:alert(1)", "published": "2026-06-20", "snippet": "", "provider": "rss",
    }  # fmt: skip
    html = _run_with_news(cfg, synthetic_parquet, tmp_path, [evil])
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "javascript:" not in html
    assert "&lt;b&gt;Fonte&lt;/b&gt;" in html
