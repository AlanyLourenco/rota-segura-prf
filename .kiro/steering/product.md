---
inclusion: always
---
# Produto — Rota Segura Analytics (PoC)

Agente de IA generativa que gera um **relatório de segurança nas rodovias federais** (Brasil ou uma UF)
a partir da base aberta de acidentes da PRF + notícias recentes.

## O que o relatório entrega
- Variação de acidentes: período atual (últimos 30 dias **disponíveis**) vs. 30 dias imediatamente anteriores.
- Taxa de letalidade = mortos / acidentes × 100.
- Taxa de gravidade = acidentes com ≥1 ferido grave ou morto / acidentes.
- Top 5 causas e top 5 trechos (UF + BR + km).
- Gráfico diário (últimos 30 dias disponíveis) e mensal (últimos 12 meses).
- Comentários do LLM separando **[BASE PRF]** de **[NOTÍCIA]**.

## Regras inegociáveis (critérios de avaliação)
1. Números vêm **só** de código determinístico (SQL/DuckDB). O LLM nunca calcula métricas.
2. O período coberto é explícito no relatório (base atrasa ~1 mês; ano corrente é preliminar).
3. Nenhum dado por pessoa chega ao LLM. Só agregados, com supressão de células pequenas (LGPD).
4. O agente não atribui causa a acidente citado em notícia se isso não estiver na base.
5. Toda decisão do agente (tool call, prompt, resposta, guardrail) é registrada em trilha de auditoria JSONL.

## Critérios de avaliação do desafio
Arquitetura · Governança/transparência · Guardrails · Uso de tools · Dados sensíveis · Clean code.
