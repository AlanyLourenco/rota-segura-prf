"""Construção dos LLMs do agente: cadeia de modelos com fallback e orquestrador opcionalmente determinístico.

A cota gratuita do Gemini é por **requisições/dia por modelo** (não por tokens). Por isso:
- `LLM_MODEL` aceita uma lista separada por vírgula; se o primeiro falhar (ex.: 429), o próximo responde.
  Como cada modelo tem cota própria, a lista multiplica os relatórios possíveis por dia.
- `ORCHESTRATOR_MODEL=offline` troca o orquestrador (3 chamadas por relatório) pelo plano fixo de tools;
  só o redator usa LLM. Vazio = mesma cadeia de `LLM_MODEL`.
"""

from __future__ import annotations

from typing import Any


def parse_models(spec: str) -> list[str]:
    return [m.strip() for m in spec.split(",") if m.strip()]


class ModelChain:
    """Mesma interface usada pelo grafo (`bind_tools`, `with_structured_output`), aplicada a cada modelo da
    lista e encadeada com `with_fallbacks` — o fallback acontece depois do bind, como o LangChain exige."""

    def __init__(self, llms: list[Any], names: list[str]):
        if not llms:
            raise ValueError("Nenhum modelo configurado em LLM_MODEL.")
        self.llms, self.names = llms, names
        self.model_name = " → ".join(names)

    def _chain(self, runnables: list[Any]) -> Any:
        return runnables[0] if len(runnables) == 1 else runnables[0].with_fallbacks(runnables[1:])

    def bind_tools(self, tools: list[Any]) -> Any:
        return self._chain([llm.bind_tools(tools) for llm in self.llms])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return self._chain([llm.with_structured_output(schema, **kwargs) for llm in self.llms])


def init_chain(spec: str) -> ModelChain:
    from langchain.chat_models import init_chat_model

    names = parse_models(spec)
    # max_retries baixo: 429 de cota diária não se resolve esperando; melhor cair logo no próximo modelo.
    llms = [init_chat_model(name, temperature=0, max_retries=1) for name in names]
    return ModelChain(llms, names)


def answered_by(message: Any, default: str) -> str:
    """Modelo que de fato respondeu (com fallback, pode não ser o primeiro da lista)."""
    meta = getattr(message, "response_metadata", None) or {}
    return meta.get("model_name") or meta.get("model") or default
