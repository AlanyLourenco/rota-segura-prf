"""Gera docs/arquitetura.pdf (diagrama conceitual). Uso: python docs/make_architecture_pdf.py"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

COLORS = {
    "agent": "#1f4e79",
    "llm": "#7b3fa0",
    "tool": "#2e7d32",
    "guard": "#c62828",
    "data": "#ef6c00",
    "gov": "#455a64",
    "io": "#5d4037",
}


def box(ax, x, y, w, h, text, kind, fontsize=7.4):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.15", fc=COLORS[kind], ec="white", alpha=0.92
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color="white", fontsize=fontsize, wrap=True)
    return (x, y, w, h)


def arrow(ax, a, b, text="", style="-|>", color="#333", dashed=False, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            a, b, arrowstyle=style, mutation_scale=12, color=color, lw=1.2,
            linestyle="--" if dashed else "-", connectionstyle=f"arc3,rad={rad}",
        )
    )  # fmt: skip
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.12, text, fontsize=7, ha="center", color=color)


def main() -> Path:
    fig, ax = plt.subplots(figsize=(16.5, 10.5))
    ax.set_xlim(0, 22)
    ax.set_ylim(0, 14)
    ax.axis("off")
    ax.text(
        11, 13.5, "Rota Segura Analytics — Arquitetura do agente de segurança viária",
        ha="center", fontsize=15, weight="bold",
    )  # fmt: skip
    ax.text(
        11, 13.05, "LangGraph · híbrido determinístico + LLM · números só via código · auditoria em todos os nós",
        ha="center", fontsize=9.5, color="#555",
    )  # fmt: skip

    # Fluxo principal (linha central)
    user = box(ax, 0.3, 9.6, 2.2, 1.1, "Usuário / CLI\nrelatório Brasil ou UF\n(+ foco opcional)", "io")
    ig = box(ax, 3.2, 9.6, 2.4, 1.1, "Input Guard\nUF válida · anti-injeção\nescopo · PII", "guard")
    orch = box(ax, 6.4, 9.3, 3.2, 1.7, "AGENTE ORQUESTRADOR\n(nó LangGraph)\ndecide quais tools chamar\nlimite de passos", "agent", 8.5)
    llm1 = box(ax, 6.6, 11.35, 2.8, 0.9, "LLM (tool calling)\ninit_chat_model(LLM_MODEL)", "llm")
    collect = box(ax, 10.4, 9.6, 2.4, 1.1, "Collect\ngarante insumos\n(fallback auditado)", "agent")
    writer = box(ax, 13.6, 9.6, 2.4, 1.1, "Writer\nsaída estruturada\n(Draft JSON + fontes)", "agent")
    llm2 = box(ax, 13.6, 11.35, 2.4, 0.9, "LLM (redação)\nprompt versionado", "llm")
    og = box(ax, 16.8, 9.6, 2.4, 1.1, "Output Guard\nnºs rastreáveis · fontes\ncausa≠notícia · PII", "guard")
    render = box(ax, 19.6, 9.6, 2.1, 1.1, "Render\nrelatorio.md\n+ gráficos PNG", "io")
    sanitize = box(ax, 16.8, 7.9, 2.4, 0.9, "Sanitize\nremove parágrafos reprovados", "guard")

    arrow(ax, (2.5, 10.15), (3.2, 10.15))
    arrow(ax, (5.6, 10.15), (6.4, 10.15), "aprovado")
    arrow(ax, (8.0, 11.0), (8.0, 11.35), style="<|-|>")
    arrow(ax, (9.6, 10.15), (10.4, 10.15), "PRONTO")
    arrow(ax, (12.8, 10.15), (13.6, 10.15))
    arrow(ax, (14.8, 10.7), (14.8, 11.35), style="<|-|>")
    arrow(ax, (16.0, 10.15), (16.8, 10.15))
    arrow(ax, (19.2, 10.15), (19.6, 10.15), "ok")
    arrow(ax, (17.4, 10.7), (15.6, 10.7), "reprovado → retry (≤3)", color=COLORS["guard"], rad=0.5)
    arrow(ax, (18.0, 9.6), (18.0, 8.8), "tentativas esgotadas", color=COLORS["guard"])
    arrow(ax, (19.2, 8.35), (20.6, 9.6), color=COLORS["guard"])

    # Tools
    ax.text(8.0, 8.55, "TOOLS (código determinístico; LLM recebe só resumo filtrado)", ha="center", fontsize=9, weight="bold")
    t1 = box(ax, 3.0, 6.9, 2.9, 1.2, "get_road_safety_metrics\nvariação · letalidade · gravidade\ntop 5 causas e trechos", "tool")
    t2 = box(ax, 6.2, 6.9, 2.6, 1.2, "build_report_charts\ndiário (30 dias disp.)\nmensal (12 meses)", "tool")
    t3 = box(ax, 9.1, 6.9, 2.6, 1.2, "search_road_news\nacidentes · operações PRF\nferiados · obras", "tool")
    t4 = box(ax, 12.0, 6.9, 2.6, 1.2, "get_victim_profile\nagregado + supressão\nn<5 (LGPD)", "tool")
    for t in (t1, t2, t3, t4):
        arrow(ax, (8.0, 9.3), (t[0] + t[2] / 2, t[1] + t[3]), style="<|-|>", color=COLORS["tool"])

    # Dados e fontes
    priv = box(ax, 3.0, 4.6, 11.6, 1.0, "Camada de privacidade (data/privacy.py): allowlist de campos ao LLM · campos proibidos (idade exata, "
               "lat/long, ids, placa, CPF)\nbase por pessoa agregada NA INGESTÃO (faixa etária, sexo, estado físico) · supressão de células pequenas", "guard", 6.6)
    duck = box(ax, 3.0, 2.6, 4.2, 1.3, "DuckDB + Parquet\nacidentes.parquet\npessoas_agregado.parquet", "data")
    ingest = box(ax, 3.0, 0.5, 4.2, 1.4, "Ingestão (data/ingest.py)\nlatin-1 · ';' · vírgula decimal · km texto\ncausas normalizadas · flag preliminar", "data")
    prf = box(ax, 0.2, 0.5, 2.4, 1.4, "Dados Abertos PRF\n(Google Drive)\nCSV anual", "data")
    news = box(ax, 9.1, 2.6, 3.4, 1.3, "Fontes de notícias\nTavily (se chave) →\nGoogle News RSS · Agência Gov RSS", "data")
    arrow(ax, (2.6, 1.2), (3.0, 1.2))
    arrow(ax, (5.1, 1.9), (5.1, 2.6))
    arrow(ax, (5.1, 3.9), (5.1, 4.6))
    arrow(ax, (10.8, 3.9), (10.8, 4.6))
    arrow(ax, (4.45, 5.6), (4.45, 6.9))
    arrow(ax, (10.4, 5.6), (10.4, 6.9))
    arrow(ax, (13.3, 5.6), (13.3, 6.9))
    ax.text(12.6, 3.25, "conteúdo tratado como\ndado não confiável:\nlimpeza · PII mascarada", fontsize=7, color="#555")

    # Governança
    gov = box(ax, 15.6, 0.5, 6.1, 5.6, "", "gov")
    ax.text(18.65, 5.7, "GOVERNANÇA E TRANSPARÊNCIA", ha="center", color="white", fontsize=10, weight="bold")
    ax.text(
        15.9, 5.3,
        "AuditLogger (audit/<run_id>.jsonl, append-only)\n"
        "• start/end/erro + duração de cada nó\n"
        "• cada chamada LLM: modelo, versão do prompt,\n  sha256 do prompt, tool_calls, uso de tokens\n"
        "• cada tool: argumentos e saída\n"
        "• decisões: guardrail aprovado/reprovado,\n  fallback, tool bloqueada, sanitização\n\n"
        "Manifesto (audit/<run_id>.manifest.json)\n"
        "• sha256 da base · período coberto · fontes\n"
        "• resultado dos guardrails · tentativas · avisos\n\n"
        "Relatório: seção Transparência + rótulos\n[BASE PRF] / [NOTÍCIA n] por parágrafo",
        va="top", color="white", fontsize=8.2, family="monospace",
    )  # fmt: skip
    arrow(ax, (20.6, 9.6), (20.6, 6.1), "eventos de todos os nós", color=COLORS["gov"], dashed=True)

    # Legenda
    for i, (kind, label) in enumerate([("agent", "nós do agente"), ("llm", "LLM"), ("tool", "tools"),
                                       ("guard", "guardrails / privacidade"), ("data", "dados e fontes"),
                                       ("gov", "auditoria")]):  # fmt: skip
        ax.add_patch(FancyBboxPatch((0.3 + i * 2.5, 12.45), 0.25, 0.25, boxstyle="round,pad=0.02", fc=COLORS[kind]))
        ax.text(0.7 + i * 2.5, 12.57, label, fontsize=7.5, va="center")
    out = Path(__file__).parent / "arquitetura.pdf"
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(main())
