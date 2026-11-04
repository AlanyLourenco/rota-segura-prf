# Design

## Visão geral
Arquitetura **híbrida determinística + agente**: o LLM orquestra e redige; todo número é produzido por código.

```
usuário ──► input_guard ──► orchestrator (LLM + tools) ──► writer (LLM, saída estruturada)
                                 │  tools:                          │
                                 │  • get_metrics(uf)   → DuckDB    ▼
                                 │  • build_charts(uf)  → PNG     output_guard ──(falha, retry ≤2)──► writer
                                 │  • search_news(uf,q) → Tavily/RSS │
                                 │  • get_victim_profile(uf) → agregado LGPD
                                 ▼                                   ▼
                           audit.jsonl ◄──── todos os nós ────►  render (Markdown)
```

## Componentes
| Componente | Responsabilidade | Decisão |
|---|---|---|
| `data/ingest.py` | download + normalização → Parquet | Parquet + DuckDB: rápido, sem servidor, SQL auditável |
| `metrics.py` | `MetricsBundle` (pydantic) | SQL puro; testável sem LLM |
| `agent/graph.py` | `StateGraph` LangGraph | nós explícitos > ReAct livre: previsível e auditável |
| `guardrails.py` | entrada (UF, injeção) e saída (números, PII, causa-notícia, rótulos) | regras determinísticas, baratas e explicáveis |
| `audit.py` | JSONL + manifesto | append-only, um arquivo por `run_id` |
| `news.py` | `NewsItem` | conteúdo de notícia é tratado como **dado não confiável** (delimitado no prompt) |

## Estado do grafo (`ReportState`)
`run_id, uf, metrics, charts, news, victim_profile, draft, guard_report, attempts, final_markdown`.

## Fluxo de dados sensíveis
CSV por pessoa → `privacy.aggregate_people()` (faixa etária, sexo, estado físico; n<5 → "<5") → LLM.
Campos permitidos ao LLM: ver `privacy.LLM_ALLOWED_FIELDS`.

## Validação de saída (writer → output_guard)
O writer devolve JSON `{sections:[{title, paragraphs:[{text, sources:["BASE"|"NEWS:n"]}]}]}`.
1. Todo parágrafo precisa ter `sources` não vazio e IDs de notícia existentes.
2. Todo número precisa bater (tolerância de arredondamento) com o `MetricsBundle` (se o parágrafo cita BASE) ou com título/snippet/data das notícias citadas.
3. Parágrafo com fonte só-NEWS não pode conter vocabulário de causa da base ("causa", nomes de causas).
4. Regex de PII (CPF, placa Mercosul/antiga, e-mail, telefone).

## Interface web (R9)
`rota-segura web` → FastAPI em 127.0.0.1. `GET /api/stream` roda `service.run_report` numa thread e transmite por SSE cada evento do `AuditLogger` (via `listener`), terminando com `done` (chave do relatório) ou `failed` (status + motivo). `GET /api/runs` lista relatórios em `reports/` e `GET /api/runs/{key}` devolve HTML saneado, eventos do JSONL e manifesto. O frontend é estático (HTML/CSS/JS sem build), sob CSP `script-src 'self'`.

## Modo rota (R10)
`route.py`: `plan_route(origem, destino)` → Nominatim (geocodificação, `countrycodes=br`) + OSRM (`steps`, geometria GeoJSON) → `RoutePlan` (cidades, UF, distância, BRs dos `ref` dos passos, coordenadas). Injetável (`ToolContext.router`) para testes.
Nó determinístico `route` entre `input_guard` e `orchestrator`: chama o roteador, depois `MetricsEngine.route_segments` (grade de ~1,1 km sobre o traçado densificado, dilatada em 1 célula; acidentes das BRs da rota com lat/lon na grade → intervalos de km por UF+BR, unindo lacunas ≤ 5 km). Sem BR ou sem trecho → `RouteNotCovered` (status `not_covered`).
`MetricsEngine.compute(uf, segments, period_days)` filtra por `OR` de `(uf, br, km BETWEEN)`. Perfil de vítimas não se aplica à rota (base por pessoa só tem UF). Notícias usam as BRs da rota na busca.

## Testes
Unitários para ingestão (parsing), métricas (fixture sintética), privacidade, guardrails, e o grafo em modo offline.
Conjunto golden `evals/golden_guardrails.json` (casos de entrada/saída com decisão esperada), rodado no pytest e em `rota-segura eval`.
