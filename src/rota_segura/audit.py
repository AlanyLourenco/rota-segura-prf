"""Trilha de auditoria append-only (JSONL) e manifesto por execução.

Cada evento registra: quem (nó/tool), o quê (entrada resumida, saída resumida), por quê (decisão/motivo),
quando (timestamp, duração) e com qual modelo/prompt. Arquivos: `audit/<run_id>.jsonl` e
`audit/<run_id>.manifest.json`.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_STR = 2000


def _summarize(value: Any) -> Any:
    """Trunca strings longas para manter a trilha legível sem perder rastreabilidade (hash)."""
    if isinstance(value, str) and len(value) > _MAX_STR:
        digest = hashlib.sha256(value.encode()).hexdigest()[:12]
        return f"{value[:_MAX_STR]}… [truncado, {len(value)} chars, sha256:{digest}]"
    if isinstance(value, dict):
        return {k: _summarize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_summarize(v) for v in value]
    return value


class AuditLogger:
    def __init__(self, audit_dir: Path, run_id: str | None = None) -> None:
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        audit_dir.mkdir(parents=True, exist_ok=True)
        self.path = audit_dir / f"{self.run_id}.jsonl"
        self.manifest_path = audit_dir / f"{self.run_id}.manifest.json"
        self._seq = 0
        self.manifest: dict[str, Any] = {"run_id": self.run_id, "started_at": _now()}

    def log(self, event: str, node: str, **data: Any) -> None:
        self._seq += 1
        record = {
            "run_id": self.run_id,
            "seq": self._seq,
            "ts": _now(),
            "event": event,
            "node": node,
            **_summarize(data),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def step(self, node: str, **inputs: Any):
        """Registra início/fim/erro de um passo com duração."""
        start = time.perf_counter()
        self.log("start", node, inputs=inputs)
        try:
            yield
        except Exception as exc:
            self.log(
                "error",
                node,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round(1000 * (time.perf_counter() - start)),
            )
            raise
        self.log("end", node, duration_ms=round(1000 * (time.perf_counter() - start)))

    def decision(self, node: str, decision: str, reason: str, **data: Any) -> None:
        """Decisões explícitas (ex.: guardrail reprovou, fallback acionado, tool escolhida)."""
        self.log("decision", node, decision=decision, reason=reason, **data)

    def write_manifest(self, **data: Any) -> Path:
        self.manifest.update(_summarize(data))
        self.manifest["finished_at"] = _now()
        self.manifest["events"] = self._seq
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return self.manifest_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
