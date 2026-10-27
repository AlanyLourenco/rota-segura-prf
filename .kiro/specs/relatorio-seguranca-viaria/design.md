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
2. Números no texto rotulado BASE precisam bater (tolerância de arredondamento) com o `MetricsBundle`.
3. Parágrafo com fonte só-NEWS não pode conter vocabulário de causa da base ("causa", nomes de causas).
4. Regex de PII (CPF, placa Mercosul/antiga, e-mail, telefone).

## Testes
Unitários para ingestão (parsing), métricas (fixture sintética), privacidade, guardrails, e o grafo em modo offline.
