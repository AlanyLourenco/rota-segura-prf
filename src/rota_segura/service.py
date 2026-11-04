"""Execução de um relatório de ponta a ponta, compartilhada pela CLI e pela interface web.

Uma única função monta o grafo, roda, grava manifesto e snapshot de notícias e devolve o resultado como
dado (`RunResult`), em vez de imprimir ou levantar: quem chama decide como mostrar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rota_segura.config import Settings
from rota_segura.guardrails import InputRejected, RouteNotCovered


@dataclass
class RunResult:
    status: Literal["ok", "rejected", "not_covered", "error"]
    run_id: str
    manifest_path: Path
    audit_path: Path
    report_path: Path | None = None
    reason: str | None = None


def build_llms(cfg: Settings, offline: bool):
    if offline:
        from rota_segura.agent.offline import OfflineOrchestrator, OfflineWriter

        return OfflineOrchestrator(), OfflineWriter()
    from rota_segura.agent.offline import OfflineOrchestrator
    from rota_segura.llm import init_chain

    writer = init_chain(cfg.llm_model)
    orch_spec = cfg.orchestrator_model.strip()
    if orch_spec.lower() == "offline":
        return OfflineOrchestrator(), writer
    return (init_chain(orch_spec) if orch_spec else writer), writer


def run_report(
    cfg: Settings,
    *,
    uf: str | None = None,
    focus: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    offline: bool = False,
    no_news: bool = False,
    news_from: Path | None = None,
    out_dir: Path | None = None,
    engine: Any = None,
    router: Callable[[str, str], Any] | None = None,
    listener: Callable[[dict[str, Any]], None] | None = None,
) -> RunResult:
    from rota_segura.agent.graph import AgentDeps, build_graph
    from rota_segura.agent.tools import ToolContext
    from rota_segura.audit import AuditLogger
    from rota_segura.data.ingest import file_sha256
    from rota_segura.metrics import MetricsEngine
    from rota_segura.news import save_news

    audit = AuditLogger(cfg.audit_dir, listener=listener)
    scope = "ROTA" if origin or destination else (uf or "BR").strip().upper() or "BR"
    out_dir = out_dir or cfg.reports_dir / f"{scope}-{audit.run_id}"

    def result(status, **kw) -> RunResult:
        return RunResult(status, audit.run_id, audit.manifest_path, audit.path, **kw)

    try:
        orchestrator_llm, writer_llm = build_llms(cfg, offline)
        ctx = ToolContext(
            cfg=cfg, engine=engine or MetricsEngine(cfg=cfg), uf=None, output_dir=out_dir, offline_news=no_news,
            news_snapshot=news_from,
        )  # fmt: skip
        if router:
            ctx.router = router
        app = build_graph(AgentDeps(ctx=ctx, audit=audit, orchestrator_llm=orchestrator_llm, writer_llm=writer_llm))
        state = {"uf": uf, "focus": focus, "origin": origin, "destination": destination}
        final = app.invoke(state, {"recursion_limit": 40})
    except RouteNotCovered as exc:
        audit.write_manifest(status="not_covered", reason=str(exc), route=ctx.route.model_dump() if ctx.route else None)
        return result("not_covered", reason=str(exc))
    except InputRejected as exc:
        audit.decision("input_guard", "rejeitado", str(exc))
        audit.write_manifest(status="rejected", reason=str(exc))
        return result("rejected", reason=str(exc))
    except Exception as exc:  # falha do provedor de LLM (cota, indisponibilidade) fica registrada
        reason = f"{type(exc).__name__}: {str(exc)[:500]}"
        audit.write_manifest(status="error", reason=reason, llm_model=cfg.llm_model)
        return result("error", reason=reason)

    if ctx.route:  # R10.6: rota resolvida (cidades, BRs, trechos) junto do relatório
        (out_dir / "rota.json").write_text(ctx.route.model_dump_json(indent=2), encoding="utf-8")
    news_snapshot = out_dir / "noticias.json"
    news_sha256 = save_news(ctx.news or [], news_snapshot)
    report_path = Path(final["report_path"])
    audit.write_manifest(
        status="ok", news_snapshot=news_snapshot, news_sha256=news_sha256, news_replayed=news_from is not None,
        scope=ctx.metrics.scope, focus=final.get("focus"), offline=offline,
        route=ctx.route.model_dump() if ctx.route else None,
        llm_model=cfg.llm_model if not offline else "offline",
        data_sha256=file_sha256(cfg.occurrences_parquet), data_max_date=ctx.metrics.data_max_date,
        period=ctx.metrics.period.model_dump(), guard_passed=final["guard"].passed,
        writer_attempts=final["attempts"], warnings=final["warnings"],
        news_sources=[{"id": n.id, "url": n.url, "provider": n.provider} for n in ctx.news or []],
        report=report_path,
    )  # fmt: skip
    return result("ok", report_path=report_path)
