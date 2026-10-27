"""LLMs determinísticos para rodar sem chave de API (demo, testes e CI).

Implementam a mesma interface usada pelo grafo (`bind_tools`, `with_structured_output`, `invoke`), então o
fluxo, a auditoria e os guardrails são exercitados exatamente como com um LLM real.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from rota_segura.guardrails import BASE_SOURCE, Draft, Paragraph, Section

_PLAN = ["get_road_safety_metrics", "build_report_charts", "get_victim_profile", "search_road_news"]


class OfflineOrchestrator:
    model_name = "offline:scripted-orchestrator"

    def bind_tools(self, tools):  # noqa: D401 - mesma assinatura do LangChain
        return self

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        done = {m.name for m in messages if isinstance(m, ToolMessage)}
        pending = [name for name in _PLAN if name not in done]
        if not pending:
            return AIMessage(content="PRONTO")
        name = pending[0]
        return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": f"offline-{name}"}])


class OfflineWriter:
    model_name = "offline:template-writer"

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages: list[BaseMessage]) -> Draft:
        text = messages[-1].content
        m = json.loads(re.search(r"<metricas>\s*(.*?)\s*</metricas>", text, re.S).group(1))
        news = json.loads(re.search(r"<noticias>\s*(.*?)\s*</noticias>", text, re.S).group(1))
        return _template_draft(m, news)


def _fmt(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _template_draft(m: dict, news: list[dict]) -> Draft:
    var = m["variation_pct"]
    trend = "estável" if var is None or abs(var) < 1 else ("alta" if var > 0 else "queda")
    var_txt = "sem base de comparação" if var is None else f"{_fmt(var)}%"
    causes = m["top_causes"]
    segs = m["top_segments"]
    overview = Paragraph(sources=[BASE_SOURCE], text=(
        f"Em {m['scope']}, foram registrados {m['total_accidents']} acidentes no período, contra "
        f"{m['previous_total']} no período anterior ({var_txt}), indicando tendência de {trend}. "
        f"A letalidade foi de {_fmt(m['lethality_rate'])} mortes por 100 acidentes e "
        f"{_fmt(m['severity_rate'])}% dos acidentes tiveram feridos graves ou mortos."
    ))  # fmt: skip
    sections = [Section(title="Visão geral", paragraphs=[overview])]
    if causes:
        top = causes[0]
        sections.append(Section(title="Causas e trechos críticos", paragraphs=[Paragraph(
            sources=[BASE_SOURCE],
            text=(f"A causa mais frequente na base foi \"{top['cause']}\", com {top['accidents']} acidentes "
                  f"({_fmt(top['share_pct'])}% do total). "
                  + (f"O trecho mais crítico foi {segs[0]['uf']} BR-{segs[0]['br']} km {segs[0]['km']}, "
                     f"com {segs[0]['accidents']} acidentes." if segs else "")),
        )]))  # fmt: skip
    if news:
        n = news[0]
        sections.append(Section(title="Contexto das notícias", paragraphs=[Paragraph(
            sources=[f"NEWS:{n['id']}"],
            text=f"Entre as notícias recentes, destaca-se: \"{n['title']}\" ({n['source']}). "
                 "A notícia é apresentada como contexto e não foi cruzada com registros individuais da base.",
        )]))  # fmt: skip
    return Draft(
        headline=f"{m['scope']}: {m['total_accidents']} acidentes nos últimos 30 dias disponíveis "
        f"({var_txt} frente ao período anterior).",
        sections=sections,
    )
