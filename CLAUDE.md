# CLAUDE.md

Agente LangGraph que gera relatório de segurança viária (PRF) — PoC "Rota Segura Analytics".

## Fonte da verdade (leia só o necessário — economize tokens)
- Escopo/regras: `.kiro/steering/product.md` (sempre)
- Stack e comandos: `.kiro/steering/tech.md`
- Onde fica cada coisa: `.kiro/steering/structure.md`
- Requisitos EARS / design / tarefas: `.kiro/specs/relatorio-seguranca-viaria/{requirements,design,tasks}.md`

Fluxo de trabalho (SDD): requisito → design → tarefa → código → teste → marcar `[x]` em `tasks.md`.
Mudança de escopo? Atualize a spec **antes** do código.

## Regras inegociáveis
- LLM nunca calcula números: métricas só em `metrics.py` (DuckDB).
- Nada por pessoa ao LLM; passar por `data/privacy.py`.
- Todo nó/tool registra evento via `audit.AuditLogger`.
- Texto gerado sempre com rótulos `[BASE PRF]` / `[NOTÍCIA n]`; validado em `guardrails.py`.

## Comandos
```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check src tests
.venv/Scripts/python -m rota_segura.cli report --uf SC --offline
```

## Economia de tokens
- Não leia `data/`, `reports/`, `audit/` nem `.venv/`.
- Use Grep/Glob direcionados; não releia arquivos já em contexto.
- Respostas curtas; diffs pequenos.
