"""CLI: `rota-segura ingest`, `report [--uf SC] [--focus ...] [--offline]`, `eval` e `web` (interface local)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rota_segura.config import settings


def cmd_ingest(args: argparse.Namespace) -> int:
    from rota_segura.data.ingest import ingest

    for name, path in ingest(years=args.years, force=args.force).items():
        print(f"{name}: {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from rota_segura.service import run_report

    result = run_report(
        settings, uf=args.uf, focus=args.focus, offline=args.offline, no_news=args.no_news,
        news_from=Path(args.news_from) if args.news_from else None, out_dir=Path(args.out) if args.out else None,
    )  # fmt: skip
    if result.status == "rejected":
        print(f"Requisição rejeitada: {result.reason}", file=sys.stderr)
        return 2
    if result.status == "error":
        print(f"Falha na execução (registrada em {result.manifest_path}): {result.reason[:200]}", file=sys.stderr)
        return 1
    print(f"Relatório: {result.report_path}\nAuditoria: {result.audit_path}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import webbrowser

    import uvicorn

    from rota_segura.web.app import create_app

    url = f"http://127.0.0.1:{args.port}"
    print(f"Rota Segura PRF em {url} (Ctrl+C para encerrar)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from rota_segura.evals import DEFAULT_CASES, run_suite

    result = run_suite(Path(args.cases) if args.cases else DEFAULT_CASES)
    for category, (ok, total) in sorted(result.by_category.items()):
        print(f"{category:<10} {ok}/{total}")
    for r in result.results:
        if not r.ok:
            print(f"FALHOU {r.id} (regras obtidas: {r.got_rules})")
    print(f"total      {result.ok}/{result.total}")
    return 0 if result.ok == result.total else 1


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
    p_report.add_argument("--news-from", help="Reusa o snapshot noticias.json de uma execução anterior")
    p_report.add_argument("--out", help="Diretório de saída")
    p_report.set_defaults(func=cmd_report)

    p_eval = sub.add_parser("eval", help="Roda o conjunto golden dos guardrails")
    p_eval.add_argument("--cases", help="Arquivo JSON de casos (padrão: evals/golden_guardrails.json)")
    p_eval.set_defaults(func=cmd_eval)

    p_web = sub.add_parser("web", help="Abre a interface web local (127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.add_argument("--no-browser", action="store_true", help="Não abre o navegador automaticamente")
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
