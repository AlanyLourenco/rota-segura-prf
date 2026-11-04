"""Interface web local (R9): formulário, agente ao vivo (eventos da auditoria via SSE) e relatório.

Não há lógica de negócio aqui: tudo passa por `service.run_report`, o mesmo fluxo da CLI. O servidor só
escuta em 127.0.0.1 (ver `cli.cmd_web`). O relatório inclui títulos de notícias da internet, então o
Markdown é convertido sem HTML bruto e só com links http(s); a página roda sob CSP restrita.
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import markdown
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from rota_segura.config import VALID_UFS, Settings
from rota_segura.config import settings as default_settings
from rota_segura.service import run_report

STATIC = Path(__file__).parent / "static"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Sem isso o navegador guarda app.js/style.css por heurística e mistura versão nova do HTML com JS antigo.
    "Cache-Control": "no-cache",
}
# relatorio.html: sem script nenhum; só CSS inline e imagens embutidas; pode ser exibido em iframe da própria app.
REPORT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'self'"
)
LLM_KEY_VARS = ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY")
_FILE_TYPES = {".png", ".json", ".md", ".html"}
_RUN_ID = re.compile(r"Execução:\*\* `([\w-]+)`")
_BARE_FILE = re.compile(r"^[\w.-]+$")
_HTTP_URL = re.compile(r"^https?://", re.I)
_HEARTBEAT_S = 15


# --------------------------------------------------------------------------- Markdown seguro


class _SafeTree(Treeprocessor):
    """Imagens só do próprio relatório; links só http(s), abrindo em nova aba sem referrer."""

    def __init__(self, md: markdown.Markdown, key: str) -> None:
        super().__init__(md)
        self.key = key

    def run(self, root: Element) -> None:
        for el in root.iter():
            if el.tag == "img":
                src = el.get("src", "")
                if _BARE_FILE.match(src):
                    el.set("src", f"/files/{self.key}/{src}")
                else:
                    el.attrib.pop("src", None)
            elif el.tag == "a":
                if _HTTP_URL.match(el.get("href", "")):
                    el.set("target", "_blank")
                    el.set("rel", "noopener noreferrer")
                else:
                    el.attrib.pop("href", None)


class _SafeExtension(Extension):
    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key

    def extendMarkdown(self, md: markdown.Markdown) -> None:  # noqa: N802 (API do Python-Markdown)
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        md.treeprocessors.register(_SafeTree(md, self.key), "safe_tree", 15)  # depois do 'inline' (20)


def render_markdown(text: str, key: str) -> str:
    return markdown.markdown(text, extensions=["tables", _SafeExtension(key)])


# --------------------------------------------------------------------------- execuções gravadas


def _within(base: Path, rel: str) -> Path | None:
    base = base.resolve()
    path = (base / rel).resolve()
    return path if path.is_relative_to(base) and path != base else None


def _audit_file(cfg: Settings, run_id: str, suffix: str) -> Path | None:
    for folder in (cfg.audit_dir, cfg.reports_dir / "exemplos" / "auditoria"):
        if (path := folder / f"{run_id}{suffix}").exists():
            return path
    return None


def _run_info(cfg: Settings, report_md: Path) -> dict[str, Any]:
    key = report_md.parent.resolve().relative_to(cfg.reports_dir.resolve()).as_posix()
    match = _RUN_ID.search(report_md.read_text(encoding="utf-8"))
    run_id = match.group(1) if match else None
    manifest_path = _audit_file(cfg, run_id, ".manifest.json") if run_id else None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
    return {
        "key": key,
        "run_id": run_id,
        "scope": manifest.get("scope") or key.split("/")[-1].split("-")[0],
        "status": manifest.get("status", "ok"),
        "model": manifest.get("llm_model"),
        "finished_at": manifest.get("finished_at"),
        "example": key.startswith("exemplos/"),
        "mtime": report_md.stat().st_mtime,
    }


def list_runs(cfg: Settings) -> list[dict[str, Any]]:
    if not cfg.reports_dir.exists():
        return []
    reports = [*cfg.reports_dir.glob("*/relatorio.md"), *cfg.reports_dir.glob("*/*/relatorio.md")]
    return sorted((_run_info(cfg, p) for p in reports), key=lambda r: r["mtime"], reverse=True)


def _events(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# --------------------------------------------------------------------------- app


def create_app(cfg: Settings = default_settings, engine_factory: Callable[[], Any] | None = None) -> FastAPI:
    app = FastAPI(title="Rota Segura PRF", docs_url=None, redoc_url=None, openapi_url=None)
    busy = threading.Lock()  # um relatório por vez: evita gastar cota do LLM em paralelo

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/files/") and request.url.path.endswith(".html"):
            response.headers["Content-Security-Policy"] = REPORT_CSP
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "ufs": sorted(VALID_UFS),
            "llm_model": cfg.llm_model,
            "llm_key_configured": any(os.getenv(var) for var in LLM_KEY_VARS),
        }

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return list_runs(cfg)

    @app.get("/api/runs/{key:path}")
    def run_detail(key: str) -> dict[str, Any]:
        folder = _within(cfg.reports_dir, key)
        if not folder or not (folder / "relatorio.md").is_file():
            raise HTTPException(404, "Relatório não encontrado.")
        info = _run_info(cfg, folder / "relatorio.md")
        manifest = _audit_file(cfg, info["run_id"], ".manifest.json") if info["run_id"] else None
        return {
            **info,
            "html": render_markdown((folder / "relatorio.md").read_text(encoding="utf-8"), info["key"]),
            # relatório didático (R9/R10); exemplos antigos só têm o Markdown
            "report_url": f"/files/{info['key']}/relatorio.html" if (folder / "relatorio.html").is_file() else None,
            "events": _events(_audit_file(cfg, info["run_id"], ".jsonl") if info["run_id"] else None),
            "manifest": json.loads(manifest.read_text(encoding="utf-8")) if manifest else None,
        }

    @app.get("/files/{path:path}")
    def files(path: str) -> FileResponse:
        target = _within(cfg.reports_dir, path)
        if not target or not target.is_file() or target.suffix not in _FILE_TYPES:
            raise HTTPException(404)
        return FileResponse(target)

    @app.get("/api/stream")
    def stream(
        uf: str = "",
        focus: str = "",
        origin: str = "",
        destination: str = "",
        offline: bool = False,
        no_news: bool = False,
    ) -> StreamingResponse:
        def events() -> Iterator[str]:
            if not busy.acquire(blocking=False):
                yield _sse("failed", {"status": "busy", "reason": "Já existe um relatório em geração. Aguarde."})
                return
            try:
                feed: queue.Queue = queue.Queue()
                outcome: dict[str, Any] = {}

                def work() -> None:
                    try:
                        outcome["result"] = run_report(
                            cfg, uf=uf or None, focus=focus or None, origin=origin or None,
                            destination=destination or None, offline=offline, no_news=no_news,
                            engine=engine_factory() if engine_factory else None, listener=feed.put,
                        )  # fmt: skip
                    except Exception as exc:  # ex.: base não ingerida
                        outcome["error"] = f"{type(exc).__name__}: {exc}"
                    finally:
                        feed.put(None)

                threading.Thread(target=work, daemon=True).start()
                while True:
                    try:
                        item = feed.get(timeout=_HEARTBEAT_S)
                    except queue.Empty:
                        yield ": ping\n\n"
                        continue
                    if item is None:
                        break
                    yield _sse("audit", item)

                result = outcome.get("result")
                if result and result.status == "ok":
                    key = result.report_path.parent.resolve().relative_to(cfg.reports_dir.resolve()).as_posix()
                    yield _sse("done", {"key": key, "run_id": result.run_id})
                else:
                    yield _sse("failed", {
                        "status": result.status if result else "error",
                        "reason": result.reason if result else outcome.get("error"),
                        "run_id": result.run_id if result else None,
                    })  # fmt: skip
            finally:
                busy.release()

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app
