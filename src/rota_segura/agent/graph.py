"""Grafo LangGraph do agente.

input_guard → orchestrator ⇄ tools → collect → writer → output_guard ─┬→ render
                                                       ↑______________│ (reprovado e tentativas < máx.)
                                                                      └→ sanitize → render (tentativas esgotadas)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from rota_segura.agent import prompts
from rota_segura.agent.tools import ToolContext, make_tools, metrics_for_llm
from rota_segura.audit import AuditLogger
from rota_segura.data.privacy import assert_llm_safe
from rota_segura.guardrails import Draft, GuardReport, numbers_in, validate_draft, validate_request
from rota_segura.news import NewsItem
from rota_segura.report import render_report

MAX_ORCHESTRATOR_STEPS = 8


class ReportState(TypedDict, total=False):
    uf: str | None
    focus: str | None
    messages: Annotated[list[BaseMessage], add_messages]
    orchestrator_steps: int
    draft: Draft | None
    guard: GuardReport | None
    attempts: int
    warnings: list[str]
    report_path: str


@dataclass
class AgentDeps:
    ctx: ToolContext
    audit: AuditLogger
    orchestrator_llm: Any
    writer_llm: Any


def _news_text(item: NewsItem) -> str:
    """Texto de onde números de uma notícia podem ser citados (inclui a data em dd/mm/aaaa)."""
    published = "/".join(reversed(item.published.split("-"))) if item.published else ""
    return f"{item.title} {item.snippet} {published}"


def _model_name(llm: Any) -> str:
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or type(llm).__name__


def _unpack_structured(result: Any) -> tuple[Draft, Any]:
    """`with_structured_output(include_raw=True)` devolve {raw, parsed, parsing_error}; o LLM offline, o Draft."""
    if isinstance(result, Draft):
        return result, None
    if result.get("parsed") is None:
        raise ValueError(f"Saída do writer fora do schema Draft: {result.get('parsing_error')}")
    return result["parsed"], result["raw"]


def build_graph(deps: AgentDeps):
    tools = {t.name: t for t in make_tools(deps.ctx)}
    orchestrator = deps.orchestrator_llm.bind_tools(list(tools.values()))
    writer = deps.writer_llm.with_structured_output(Draft, include_raw=True)
    audit, ctx, cfg = deps.audit, deps.ctx, deps.ctx.cfg

    def input_guard(state: ReportState) -> ReportState:
        with audit.step("input_guard", uf=state.get("uf"), focus=state.get("focus")):
            uf, focus = validate_request(state.get("uf"), state.get("focus"))
            audit.decision("input_guard", "aprovado", "UF e foco válidos", uf=uf, focus=focus)
        ctx.uf = uf
        task = f"Prepare os insumos do relatório para: {uf or 'Brasil'}." + (f" Foco: {focus}" if focus else "")
        return {
            "uf": uf,
            "focus": focus,
            "messages": [HumanMessage(task)],
            "orchestrator_steps": 0,
            "attempts": 0,
            "warnings": [],
        }

    def orchestrate(state: ReportState) -> ReportState:
        with audit.step("orchestrator", step=state["orchestrator_steps"] + 1):
            reply: AIMessage = orchestrator.invoke([SystemMessage(prompts.ORCHESTRATOR_SYSTEM), *state["messages"]])
            audit.log(
                "llm_call",
                "orchestrator",
                model=_model_name(deps.orchestrator_llm),
                prompt_version=prompts.PROMPT_VERSION,
                content=str(reply.content),
                tool_calls=[{"name": c["name"], "args": c["args"]} for c in reply.tool_calls],
                usage=getattr(reply, "usage_metadata", None),
            )
        return {"messages": [reply], "orchestrator_steps": state["orchestrator_steps"] + 1}

    def run_tools(state: ReportState) -> ReportState:
        last: AIMessage = state["messages"][-1]
        already = {m.name for m in state["messages"] if isinstance(m, ToolMessage)}
        results = []
        for call in last.tool_calls:
            name = call["name"]
            if name not in tools:
                output = f"ERRO: ferramenta '{name}' não existe."
                audit.decision("tools", "bloqueado", "tool fora da allowlist", tool=name)
            elif name in already:
                output = "Ferramenta já executada; use o resultado anterior."
                audit.decision("tools", "ignorado", "chamada repetida", tool=name)
            else:
                with audit.step(f"tool:{name}", args=call["args"]):
                    output = tools[name].invoke(call["args"])
                    audit.log("tool_result", f"tool:{name}", output=output)
            results.append(ToolMessage(content=output, name=name, tool_call_id=call["id"]))
        return {"messages": results}

    def route_orchestrator(state: ReportState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if state["orchestrator_steps"] >= MAX_ORCHESTRATOR_STEPS:
                audit.decision("orchestrator", "interrompido", "limite de passos atingido")
                return "collect"
            return "tools"
        return "collect"

    def collect(state: ReportState) -> ReportState:
        """Garante os insumos obrigatórios mesmo se o LLM pulou alguma tool (com registro da decisão)."""
        with audit.step("collect"):
            if ctx.metrics is None:
                audit.decision("collect", "fallback", "orquestrador não calculou métricas; executando direto")
                tools["get_road_safety_metrics"].invoke({})
            if not ctx.charts:
                audit.decision("collect", "fallback", "orquestrador não gerou gráficos; executando direto")
                tools["build_report_charts"].invoke({})
            if ctx.news is None:
                audit.decision("collect", "fallback", "orquestrador não buscou notícias; executando direto")
                tools["search_road_news"].invoke({})
        return {}

    def write(state: ReportState) -> ReportState:
        attempt = state["attempts"] + 1
        feedback = ""
        if state.get("guard") and not state["guard"].passed:
            issues = "\n".join(f"- [{i.rule}] {i.location}: {i.detail}" for i in state["guard"].issues)
            feedback = prompts.WRITER_FEEDBACK.format(issues=issues)
        news = [n.model_dump(include={"id", "title", "source", "published", "snippet"}) for n in ctx.news or []]
        payload = assert_llm_safe({"news": news, "victim_profile": ctx.victim_profile})
        user = prompts.WRITER_USER.format(
            scope=ctx.metrics.scope,
            focus=state.get("focus") or "nenhum",
            metrics_json=json.dumps(metrics_for_llm(ctx.metrics), ensure_ascii=False, indent=1),
            victim_profile_json=json.dumps(payload["victim_profile"], ensure_ascii=False),
            news_json=json.dumps(payload["news"], ensure_ascii=False, indent=1),
            feedback=feedback,
        )
        with audit.step("writer", attempt=attempt):
            result = writer.invoke([SystemMessage(prompts.WRITER_SYSTEM), HumanMessage(user)])
            draft, raw = _unpack_structured(result)
            audit.log(
                "llm_call",
                "writer",
                model=_model_name(deps.writer_llm),
                prompt_version=prompts.PROMPT_VERSION,
                prompt_sha256=hashlib.sha256(user.encode()).hexdigest(),
                output=draft.model_dump(),
                usage=getattr(raw, "usage_metadata", None),
            )
        return {"draft": draft, "attempts": attempt}

    def output_guard(state: ReportState) -> ReportState:
        with audit.step("output_guard", attempt=state["attempts"]):
            news = ctx.news or []
            report = validate_draft(
                state["draft"], ctx.metrics.numbers(), {n.id for n in news},
                news_numbers={n.id: numbers_in(_news_text(n)) for n in news},
            )  # fmt: skip
            audit.decision(
                "output_guard",
                "aprovado" if report.passed else "reprovado",
                f"{len(report.issues)} problema(s)",
                issues=[i.model_dump() for i in report.issues],
            )
        return {"guard": report}

    def route_guard(state: ReportState) -> str:
        if state["guard"].passed:
            return "render"
        return "writer" if state["attempts"] < cfg.max_writer_attempts else "sanitize"

    def sanitize(state: ReportState) -> ReportState:
        """Remove só os parágrafos reprovados; o restante (e todas as métricas) segue para o relatório."""
        bad = {i.location for i in state["guard"].issues}
        draft = state["draft"].model_copy(deep=True)
        removed = 0
        for s_idx, section in enumerate(draft.sections):
            kept = [
                p for p_idx, p in enumerate(section.paragraphs) if f"sections[{s_idx}].paragraphs[{p_idx}]" not in bad
            ]
            removed += len(section.paragraphs) - len(kept)
            section.paragraphs = kept
        draft.sections = [s for s in draft.sections if s.paragraphs]
        if "headline" in bad:
            draft.headline = f"Relatório de segurança viária — {ctx.metrics.scope}"
        warning = (
            f"{removed} trecho(s) de comentário gerado(s) pelo LLM foram removidos por não passarem "
            "nos guardrails após o máximo de tentativas. As métricas não são afetadas."
        )
        audit.decision("sanitize", "parágrafos removidos", warning, removed=removed)
        return {"draft": draft, "warnings": [*state["warnings"], warning]}

    def render(state: ReportState) -> ReportState:
        with audit.step("render"):
            path = render_report(
                metrics=ctx.metrics,
                draft=state["draft"],
                news=ctx.news or [],
                charts=ctx.charts,
                victim_profile=ctx.victim_profile,
                warnings=state["warnings"],
                run_id=audit.run_id,
                model=_model_name(deps.writer_llm),
                prompt_version=prompts.PROMPT_VERSION,
                guard=state["guard"],
                attempts=state["attempts"],
                out_dir=ctx.output_dir,
            )
            audit.log("artifact", "render", report=Path(path))
        return {"report_path": str(path)}

    graph = StateGraph(ReportState)
    for name, fn in [
        ("input_guard", input_guard),
        ("orchestrator", orchestrate),
        ("tools", run_tools),
        ("collect", collect),
        ("writer", write),
        ("output_guard", output_guard),
        ("sanitize", sanitize),
        ("render", render),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "input_guard")
    graph.add_edge("input_guard", "orchestrator")
    graph.add_conditional_edges("orchestrator", route_orchestrator, ["tools", "collect"])
    graph.add_edge("tools", "orchestrator")
    graph.add_edge("collect", "writer")
    graph.add_edge("writer", "output_guard")
    graph.add_conditional_edges("output_guard", route_guard, ["render", "writer", "sanitize"])
    graph.add_edge("sanitize", "render")
    graph.add_edge("render", END)
    return graph.compile()
