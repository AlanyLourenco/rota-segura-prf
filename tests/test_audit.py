import json

from rota_segura.audit import AuditLogger
from rota_segura.config import ROOT


def test_paths_inside_project_are_recorded_relative(tmp_path):
    audit = AuditLogger(tmp_path, run_id="t")
    audit.log("artifact", "render", report=ROOT / "reports" / "SC-x" / "relatorio.md")
    manifest_path = audit.write_manifest(news_snapshot=ROOT / "reports" / "SC-x" / "noticias.json")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    event = json.loads(audit.path.read_text("utf-8").splitlines()[-1])
    assert event["report"] == "reports/SC-x/relatorio.md"
    assert manifest["news_snapshot"] == "reports/SC-x/noticias.json"


def test_paths_outside_project_are_kept(tmp_path):
    audit = AuditLogger(tmp_path, run_id="t")
    manifest = json.loads(audit.write_manifest(report=tmp_path / "relatorio.md").read_text("utf-8"))
    assert manifest["report"] == str(tmp_path / "relatorio.md")
