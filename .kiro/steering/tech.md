---
inclusion: always
---
# Stack técnica

- Python 3.10+ · venv em `.venv` · dependências em `pyproject.toml`.
- **LangGraph** (orquestração) + **LangChain** `init_chat_model` (provedor plugável via `LLM_MODEL`,
  ex.: `anthropic:claude-sonnet-5-5`, `openai:gpt-4.1-mini`). Sem chave → modo `offline` (LLM fake determinístico).
- **DuckDB** sobre Parquet normalizado (`data/processed/acidentes.parquet`).
- **matplotlib** para gráficos (PNG) · **Jinja2** para o relatório Markdown.
- Notícias: Tavily (se `TAVILY_API_KEY`) → fallback RSS (Google News, Agência Gov). O site da PRF não tem RSS funcional..
- Testes: `pytest` · Lint: `ruff`.

## Comandos
```bash
.venv/Scripts/python -m rota_segura.cli ingest            # baixa + normaliza
.venv/Scripts/python -m rota_segura.cli report --uf SC    # gera relatório (ou sem --uf p/ Brasil; --offline sem API)
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check src tests
```

## Convenções
- Código em inglês (nomes), textos de domínio/relatório em português.
- Funções puras para métricas; I/O isolado em `data/`, `news/`, `audit/`.
- Tipos com `pydantic`/`dataclasses`; nada de dict solto atravessando camadas.
