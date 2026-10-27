"""Gráficos do relatório (PNG)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from rota_segura.metrics import MetricsBundle  # noqa: E402

_COLOR = "#1f4e79"


def build_charts(metrics: MetricsBundle, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return {"daily": _daily_chart(metrics, out_dir), "monthly": _monthly_chart(metrics, out_dir)}


def _daily_chart(metrics: MetricsBundle, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 3.8))
    days = [p.day for p in metrics.daily]
    ax.bar(days, [p.accidents for p in metrics.daily], color=_COLOR)
    ax.set_title(
        f"Acidentes por dia — {metrics.scope} — {metrics.period.label} (últimos 30 dias disponíveis)", fontsize=10
    )
    ax.set_ylabel("Acidentes")
    ax.tick_params(axis="x", rotation=60, labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, out_dir / "acidentes_diarios.png")


def _monthly_chart(metrics: MetricsBundle, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 3.8))
    months = [m.month for m in metrics.monthly]
    bars = ax.bar(months, [m.accidents for m in metrics.monthly], color=_COLOR)
    ax.bar_label(bars, fontsize=8)
    title = f"Acidentes por mês — {metrics.scope} — últimos 12 meses disponíveis"
    if metrics.data_max_date.day < 28:
        title += f" (mês {months[-1]} parcial)"
    ax.set_title(title, fontsize=10)
    ax.set_ylabel("Acidentes")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, out_dir / "acidentes_mensais.png")


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
