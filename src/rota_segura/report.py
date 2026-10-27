"""Renderização do relatório final em Markdown (Jinja2)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from rota_segura.guardrails import BASE_SOURCE, Draft, GuardReport
from rota_segura.metrics import MetricsBundle
from rota_segura.news import NewsItem


def _br(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text


def _labels(sources: list[str]) -> str:
    tags = ["[BASE PRF]" if s == BASE_SOURCE else f"[NOTÍCIA {s.split(':', 1)[1]}]" for s in sources]
    return " ".join(f"**{t}**" for t in tags)


TEMPLATE = """\
# Relatório de Segurança nas Rodovias Federais — {{ m.scope }}

> **Período coberto (base PRF):** {{ m.period.label }} — últimos {{ m.daily|length }} dias **disponíveis**.
> A base da PRF é publicada com atraso de ~1 mês; o dado mais recente disponível é de
> **{{ m.data_max_date.strftime('%d/%m/%Y') }}** (não é o calendário de hoje, {{ generated_at }}).
> **Comparação:** {{ m.previous_period.label }} (30 dias imediatamente anteriores).
{% if m.preliminary %}> ⚠️ **Dados preliminares:** o ano corrente ainda está sujeito a revisão pela PRF \
(consolidação em janeiro, revisão em março).
{% endif %}

**Resumo:** {{ draft.headline }}

{% for w in warnings %}> ⚠️ {{ w }}
{% endfor %}
## 1. Indicadores principais **[BASE PRF]**

| Indicador | Valor | Definição |
|---|---:|---|
| Acidentes no período | {{ br(m.total_accidents, 0) }} | ocorrências registradas pela PRF |
| Acidentes no período anterior | {{ br(m.previous_total, 0) }} | 30 dias imediatamente anteriores |
| Variação | {{ br(m.variation_pct) }}% | (atual − anterior) / anterior |
| Mortos | {{ br(m.deaths, 0) }} | soma de óbitos nas ocorrências |
| Taxa de letalidade | {{ br(m.lethality_rate) }} | mortos por 100 acidentes |
| Taxa de gravidade | {{ br(m.severity_rate) }}% | acidentes com ≥1 ferido grave ou morto / acidentes |

### Top {{ m.top_causes|length }} causas **[BASE PRF]**

| # | Causa | Acidentes | % do total | Mortos |
|---|---|---:|---:|---:|
{% for c in m.top_causes %}| {{ loop.index }} | {{ c.cause }} | {{ c.accidents }} | {{ br(c.share_pct) }}% | {{ c.deaths }} |
{% endfor %}
### Top {{ m.top_segments|length }} trechos críticos (UF + BR + km) **[BASE PRF]**

Trecho = segmento de 1 km (km inteiro). Ordenação: nº de acidentes; desempate por mortos e acidentes graves.

| # | Trecho | Acidentes | Mortos | Acidentes graves/fatais |
|---|---|---:|---:|---:|
{% for s in m.top_segments %}| {{ loop.index }} | {{ s.label }} | {{ s.accidents }} | {{ s.deaths }} | {{ s.severe_accidents }} |
{% endfor %}
## 2. Gráficos **[BASE PRF]**

![Acidentes diários]({{ charts.daily }})

![Acidentes mensais]({{ charts.monthly }})

{% if victim_profile %}
## 3. Perfil agregado das vítimas graves e fatais **[BASE PRF — anonimizado]**

Contagens agregadas da base "por pessoa"; células com menos de 5 pessoas aparecem como `<5` (LGPD).

{% for dim, rows in victim_profile.items() %}**{{ dim.replace('_', ' ').capitalize() }}:** \
{% for r in rows %}{{ r.estado_fisico }} · {{ r.grupo }}: {{ r.n }}{{ "; " if not loop.last }}{% endfor %}

{% endfor %}{% endif %}
## 4. Análise e contexto (gerado por IA, validado por guardrails)

Cada parágrafo indica sua fonte: **[BASE PRF]** = calculado da base oficial; **[NOTÍCIA n]** = notícia listada \
na seção 5 (contexto, sem verificação contra registros individuais da base).

{% for section in draft.sections %}### {{ section.title }}

{% for p in section.paragraphs %}{{ labels(p.sources) }} {{ p.text }}

{% endfor %}{% endfor %}
## 5. Notícias consultadas

{% for n in news %}{{ n.id }}. [{{ n.title }}]({{ n.url }}) — {{ n.source }}{% if n.published %}, \
{{ n.published }}{% endif %} _(via {{ n.provider }})_
{% else %}Nenhuma notícia relevante encontrada.
{% endfor %}
## 6. Transparência e governança

- **Execução:** `{{ run_id }}` · trilha de auditoria em `audit/{{ run_id }}.jsonl` e manifesto em \
`audit/{{ run_id }}.manifest.json`.
- **Modelo de linguagem:** `{{ model }}` · versão dos prompts `{{ prompt_version }}`.
- **Guardrails de saída:** {{ "aprovado" if guard.passed else "reprovado (ver avisos)" }} após {{ attempts }} \
tentativa(s){% if guard.issues %}; problemas: {% for i in guard.issues %}`{{ i.rule }}`{{ ", " if not loop.last }}\
{% endfor %}{% endif %}.
- **Origem dos números:** todas as métricas, tabelas e gráficos são calculados por código determinístico \
(DuckDB) sobre a base aberta da PRF; o LLM apenas redige comentários e é verificado contra esses números.
- **Notícias:** usadas apenas como contexto. O agente é proibido de atribuir causa a um acidente específico \
noticiado; causas vêm exclusivamente da base.
- **Dados pessoais (LGPD):** nenhum registro individual é enviado ao LLM; a base por pessoa é agregada na \
ingestão e células pequenas são suprimidas.
- **Fonte dos dados:** [Dados Abertos da PRF](https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf).
"""


def render_report(
    *,
    metrics: MetricsBundle,
    draft: Draft,
    news: list[NewsItem],
    charts: dict[str, Path],
    victim_profile: dict | None,
    warnings: list[str],
    run_id: str,
    model: str,
    prompt_version: str,
    guard: GuardReport,
    attempts: int,
    out_dir: Path,
) -> Path:
    env = Environment(undefined=StrictUndefined, trim_blocks=False, autoescape=False)
    env.globals.update(br=_br, labels=_labels)
    text = env.from_string(TEMPLATE).render(
        m=metrics, draft=draft, news=news, charts={k: p.name for k, p in charts.items()},
        victim_profile=victim_profile, warnings=warnings, run_id=run_id, model=model,
        prompt_version=prompt_version, guard=guard, attempts=attempts,
        generated_at=datetime.now().strftime("%d/%m/%Y"),
    )  # fmt: skip
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "relatorio.md"
    path.write_text(text, encoding="utf-8")
    return path
