"""Tools expostas ao orquestrador. Cada tool:
- executa código determinístico (o LLM só decide QUANDO chamar);
- guarda o resultado completo no `ToolContext` (usado pelo render);
- devolve ao LLM apenas um resumo compacto e já filtrado pela política de privacidade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from rota_segura.charts import build_charts
from rota_segura.config import Settings
from rota_segura.data.privacy import assert_llm_safe
from rota_segura.metrics import MetricsBundle, MetricsEngine
from rota_segura.news import NewsItem, search_news


@dataclass
class ToolContext:
    cfg: Settings
    engine: MetricsEngine
    uf: str | None
    output_dir: Path
    offline_news: bool = False
    metrics: MetricsBundle | None = None
    charts: dict[str, Path] = field(default_factory=dict)
    news: list[NewsItem] | None = None
    victim_profile: dict | None = None


def metrics_for_llm(metrics: MetricsBundle) -> dict:
    """Visão das métricas que pode ir ao LLM (sem séries diárias completas, que só poluem o contexto)."""
    data = metrics.model_dump(mode="json", exclude={"daily"})
    daily = [p.accidents for p in metrics.daily]
    data["daily"] = {"min": min(daily), "max": max(daily), "dias": len(daily)} if daily else {}
    return assert_llm_safe(data)


def make_tools(ctx: ToolContext) -> list[BaseTool]:
    @tool
    def get_road_safety_metrics() -> str:
        """Calcula as métricas oficiais (variação, letalidade, gravidade, top causas e trechos) para o escopo
        do relatório a partir da base da PRF. Deve ser a primeira ferramenta chamada."""
        ctx.metrics = ctx.engine.compute(ctx.uf)
        return json.dumps(metrics_for_llm(ctx.metrics), ensure_ascii=False)

    @tool
    def build_report_charts() -> str:
        """Gera os gráficos de acidentes diários (últimos 30 dias disponíveis) e mensais (12 meses)."""
        if ctx.metrics is None:
            return "ERRO: chame get_road_safety_metrics antes."
        ctx.charts = build_charts(ctx.metrics, ctx.output_dir)
        return json.dumps({k: p.name for k, p in ctx.charts.items()})

    @tool
    def search_road_news(focus: str = "") -> str:
        """Busca notícias recentes sobre acidentes, operações da PRF, feriados prolongados e obras em rodovias
        federais do escopo. `focus` é opcional (ex.: 'feriado', 'BR-101')."""
        ctx.news = [] if ctx.offline_news else search_news(ctx.uf, ctx.cfg.tavily_api_key, ctx.cfg.max_news)
        items = [n.model_dump(include={"id", "title", "source", "published"}) for n in ctx.news]
        return json.dumps({"news": items, "focus_ignored_if_empty": focus}, ensure_ascii=False)

    @tool
    def get_victim_profile() -> str:
        """Perfil agregado e anonimizado (faixa etária, sexo, tipo de envolvido) das vítimas graves e fatais
        no período atual. Células com menos de 5 pessoas são suprimidas (LGPD)."""
        if ctx.metrics is None:
            return "ERRO: chame get_road_safety_metrics antes."
        ctx.victim_profile = ctx.engine.victim_profile(ctx.uf, ctx.metrics.period)
        if ctx.victim_profile is None:
            return "Perfil de vítimas indisponível (base por pessoa não ingerida)."
        return json.dumps(assert_llm_safe({"victim_profile": ctx.victim_profile}), ensure_ascii=False)

    return [get_road_safety_metrics, build_report_charts, search_road_news, get_victim_profile]
