"""Interface web local (R9): rotas, streaming da auditoria e saneamento do relatório."""

import pytest
from fastapi.testclient import TestClient

from rota_segura.metrics import MetricsEngine
from rota_segura.web.app import create_app, render_markdown


@pytest.fixture
def client(cfg, synthetic_parquet):
    return TestClient(create_app(cfg, engine_factory=lambda: MetricsEngine(synthetic_parquet, cfg)))


def test_index_is_served_with_strict_csp(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "Rota Segura" in resp.text
    assert "script-src 'self'" in resp.headers["content-security-policy"]


def test_stream_offline_report_emits_audit_events_then_done(client):
    body = client.get("/api/stream", params={"uf": "SC", "offline": "1", "no_news": "1"}).text
    assert "event: audit" in body and "event: done" in body
    assert body.index("event: audit") < body.index("event: done")


def test_stream_rejected_input_emits_failed_with_reason(client):
    body = client.get("/api/stream", params={"uf": "SC", "focus": "receita de bolo", "offline": "1"}).text
    assert "event: failed" in body and "rejected" in body and "escopo" in body


def test_generated_run_is_listed_and_viewable(client):
    client.get("/api/stream", params={"uf": "SC", "offline": "1", "no_news": "1"})
    runs = client.get("/api/runs").json()
    assert runs and runs[0]["scope"] == "SC" and runs[0]["status"] == "ok"
    run = client.get(f"/api/runs/{runs[0]['key']}").json()
    assert "<table>" in run["html"] and f"/files/{runs[0]['key']}/acidentes_diarios.png" in run["html"]
    assert any(e["node"] == "render" for e in run["events"])


def test_files_route_blocks_path_traversal(client):
    assert client.get("/files/../pyproject.toml").status_code == 404
    assert client.get("/files/..%2F..%2Fpyproject.toml").status_code == 404


def test_render_markdown_drops_raw_html_and_unsafe_links():
    html = render_markdown("<script>alert(1)</script> [x](javascript:alert(1)) [ok](https://gov.br) <5", "k")
    assert "<script" not in html and "javascript:" not in html
    assert 'href="https://gov.br"' in html and "&lt;5" in html
