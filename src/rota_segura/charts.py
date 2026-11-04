"""Gráficos do relatório (PNG), todos de série única: um só azul, grade discreta, rótulos de valor diretos.

Cada gráfico sai em dois temas: claro (`nome.png`, usado no Markdown e na impressão) e escuro
(`nome_escuro.png`, chave `<nome>_dark`, usado na tela pelo relatório HTML).
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from rota_segura.metrics import MetricsBundle  # noqa: E402


@dataclass(frozen=True)
class Theme:
    key: str  # sufixo da chave no dict de gráficos
    suffix: str  # sufixo do arquivo
    bar: str
    ink: str
    muted: str
    grid: str
    surface: str


LIGHT = Theme("", "", bar="#2a78d6", ink="#0b0b0b", muted="#52514e", grid="#e1e0d9", surface="#fcfcfb")
# Escuro: mesma superfície dos cartões da interface e o passo do azul validado para fundo escuro.
DARK = Theme("_dark", "_escuro", bar="#3987e5", ink="#e7eaeb", muted="#9aa5ab", grid="#2e373c", surface="#1c2226")


def build_charts(metrics: MetricsBundle, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    for t in (LIGHT, DARK):
        charts["daily" + t.key] = _daily_chart(metrics, out_dir, t)
        charts["monthly" + t.key] = _monthly_chart(metrics, out_dir, t)
        if metrics.top_causes:
            charts["causes" + t.key] = _ranking_chart(
                [c.cause for c in metrics.top_causes], [c.accidents for c in metrics.top_causes],
                f"Principais causas — {metrics.scope}", out_dir / f"causas{t.suffix}.png", t,
            )  # fmt: skip
        if metrics.top_segments:
            charts["segments" + t.key] = _ranking_chart(
                [s.label for s in metrics.top_segments], [s.accidents for s in metrics.top_segments],
                f"Trechos com mais acidentes (1 km cada) — {metrics.scope}", out_dir / f"trechos{t.suffix}.png", t,
            )  # fmt: skip
    return charts


def _axes(figsize: tuple[float, float], t: Theme):
    fig, ax = plt.subplots(figsize=figsize, facecolor=t.surface)
    ax.set_facecolor(t.surface)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t.grid)
    ax.tick_params(colors=t.muted, labelsize=8.5, length=0)
    return fig, ax


def _title(ax, text: str, t: Theme) -> None:
    ax.set_title(text, fontsize=10.5, color=t.ink, loc="left", pad=10)


def _daily_chart(metrics: MetricsBundle, out_dir: Path, t: Theme = LIGHT) -> Path:
    fig, ax = _axes((10, 3.6), t)
    days = [p.day for p in metrics.daily]
    ax.bar(days, [p.accidents for p in metrics.daily], color=t.bar, width=0.7)
    span = f"{days[0]:%d/%m/%Y} a {days[-1]:%d/%m/%Y}" if days else metrics.period.label
    _title(ax, f"Acidentes por dia — {metrics.scope} — {span} (últimos {len(days)} dias disponíveis)", t)
    ax.tick_params(axis="x", rotation=60)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.grid(axis="y", color=t.grid, linewidth=0.8)
    ax.set_axisbelow(True)
    return _save(fig, out_dir / f"acidentes_diarios{t.suffix}.png")


def _monthly_chart(metrics: MetricsBundle, out_dir: Path, t: Theme = LIGHT) -> Path:
    fig, ax = _axes((10, 3.6), t)
    months = [m.month for m in metrics.monthly]
    labels = [f"{m[5:]}/{m[2:4]}" for m in months]  # 2026-08 -> 08/26
    bars = ax.bar(labels, [m.accidents for m in metrics.monthly], color=t.bar, width=0.7)
    ax.bar_label(bars, fontsize=8, color=t.muted, padding=2)
    title = f"Acidentes por mês — {metrics.scope} — últimos 12 meses disponíveis"
    if months and metrics.data_max_date.day < 28:
        title += f" (mês {labels[-1]} parcial)"
    _title(ax, title, t)
    ax.set_yticks([])
    return _save(fig, out_dir / f"acidentes_mensais{t.suffix}.png")


def _ranking_chart(labels: list[str], values: list[int], title: str, path: Path, t: Theme = LIGHT) -> Path:
    """Barras horizontais, maior no topo, valor escrito na ponta (dispensa eixo x)."""
    fig, ax = _axes((10, 0.55 * len(labels) + 1.0), t)
    wrapped = ["\n".join(textwrap.wrap(label, 46)) for label in labels][::-1]
    bars = ax.barh(wrapped, values[::-1], color=t.bar, height=0.6)
    ax.bar_label(bars, fontsize=9, color=t.ink, padding=4)
    ax.tick_params(axis="y", labelsize=9, labelcolor=t.ink)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, max(values) * 1.12 if values else 1)
    _title(ax, title, t)
    return _save(fig, path)


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path
