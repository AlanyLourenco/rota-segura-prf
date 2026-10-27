"""CLI: `rota-segura ingest` e `rota-segura report [--uf SC] [--focus ...] [--offline]`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rota_segura.config import settings
from rota_segura.guardrails import InputRejected


def _build_llms(offline: bool):
    if offline:
        from rota_segura.agent.offline import OfflineOrchestrator, OfflineWriter

        return OfflineOrchestrator(), OfflineWriter()
    from langchain.chat_models import init_chat_model

    llm = init_chat_model(settings.llm_model, temperature=0)
    return llm, llm


def cmd_ingest(args: argparse.Namespace) -> int:
    from rota_segura.data.ingest import ingest

    for name, path in ingest(years=args.years, force=args.force).items():
        print(f"{name}: {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from rota_segura.agent.graph import AgentDeps, build_graph
    from rota_segura.agent.tools import ToolContext
    from rota_segura.audit import AuditLogger
    from rota_segura.data.ingest import file_sha256
    from rota_segura.metrics import MetricsEngine

    audit = AuditLogger(settings.audit_dir)
    scope = (args.uf or "BR").upper()
    out_dir = Path(args.out) if args.out else settings.reports_dir / f"{scope}-{audit.run_id}"
    orchestrator_llm, writer_llm = _build_llms(args.offline)
    ctx = ToolContext(cfg=settings, engine=MetricsEngine(), uf=None, output_dir=out_dir, offline_news=args.no_news)
    app = build_graph(AgentDeps(ctx=ctx, audit=audit, orchestrator_llm=orchestrator_llm, writer_llm=writer_llm))

    try:
        final = app.invoke({"uf": args.uf, "focus": args.focus}, {"recursion_limit": 40})
    except InputRejected as exc:
        audit.decision("input_guard", "rejeitado", str(exc))
        audit.write_manifest(status="rejected", reason=str(exc))
        print(f"Requisição rejeitada: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # falha do provedor de LLM (cota, indisponibilidade) fica registrada
        reason = f"{type(exc).__name__}: {str(exc)[:500]}"
        audit.write_manifest(status="error", reason=reason, llm_model=settings.llm_model)
        print(f"Falha na execução (registrada em {audit.manifest_path}): {reason[:200]}", file=sys.stderr)
        return 1

    audit.write_manifest(
        status="ok", scope=ctx.metrics.scope, focus=final.get("focus"), offline=args.offline,
        llm_model=settings.llm_model if not args.offline else "offline",
        data_sha256=file_sha256(settings.occurrences_parquet), data_max_date=ctx.metrics.data_max_date,
        period=ctx.metrics.period.model_dump(), guard_passed=final["guard"].passed,
        writer_attempts=final["attempts"], warnings=final["warnings"],
        news_sources=[{"id": n.id, "url": n.url, "provider": n.provider} for n in ctx.news or []],
        report=final["report_path"],
    )  # fmt: skip
    print(f"Relatório: {final['report_path']}\nAuditoria: {audit.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="rota-segura", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Baixa e normaliza a base da PRF")
    p_ingest.add_argument("--years", type=int, nargs="*", help="Anos (padrão: todos configurados)")
    p_ingest.add_argument("--force", action="store_true", help="Ignora o cache e baixa de novo")
    p_ingest.set_defaults(func=cmd_ingest)

    p_report = sub.add_parser("report", help="Gera o relatório")
    p_report.add_argument("--uf", help="Sigla da UF (omita para Brasil)")
    p_report.add_argument("--focus", help="Foco opcional (ex.: 'feriados e obras')")
    p_report.add_argument("--offline", action="store_true", help="Usa LLM determinístico (sem API)")
    p_report.add_argument("--no-news", action="store_true", help="Não busca notícias (sem rede)")
    p_report.add_argument("--out", help="Diretório de saída")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
