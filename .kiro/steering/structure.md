---
inclusion: always
---
# Estrutura

```
src/rota_segura/
  config.py          # settings (env), URLs da PRF, constantes
  data/ingest.py     # download Google Drive + normalização (encoding, decimais, km, causas)
  data/causes.py     # normalização de grafias de causas entre anos
  data/privacy.py    # política LGPD: allowlist de campos + supressão de células pequenas
  metrics.py         # métricas determinísticas (DuckDB) -> MetricsBundle
  charts.py          # gráficos diário/mensal
  news.py            # busca de notícias (Tavily / RSS) -> list[NewsItem]
  route.py           # rota origem→destino (Nominatim + OSRM) -> RoutePlan / RouteInfo (R10)
  llm.py             # cadeia de modelos com fallback (LLM_MODEL em lista)
  agent/tools.py     # tools LangChain expostas ao orquestrador
  agent/prompts.py   # prompts versionados
  agent/graph.py     # grafo LangGraph: orchestrator -> tools -> writer -> guardrails -> render
  guardrails.py      # validações de entrada/saída
  audit.py           # trilha de auditoria JSONL + manifesto da execução
  report.py          # render Markdown (artefato auditável) + chama report_html
  report_html.py     # relatorio.html didático e autossuficiente (gráficos embutidos, sem JS)
  cli.py             # entrypoint (ingest, report, eval, web)
  service.py         # execução de um relatório (compartilhada por CLI e web)
  web/app.py         # interface local: FastAPI + SSE da trilha de auditoria
  web/static/        # index.html, app.js, style.css (sem build)
  evals.py           # runner do conjunto golden dos guardrails
evals/               # casos golden (JSON, dados sintéticos)
tests/               # unit tests por módulo
docs/                # arquitetura (PDF), decisões (ADR)
reports/             # relatórios gerados (exemplos versionados)
.kiro/specs/         # requirements / design / tasks (fonte da verdade do escopo)
```
