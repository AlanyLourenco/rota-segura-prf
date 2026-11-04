"""Relatório em HTML autossuficiente (um arquivo, gráficos embutidos, sem JavaScript).

É o mesmo arquivo mostrado na interface e baixado pelo usuário. Segurança: Jinja com autoescape (títulos de
notícias vêm da internet), links só http(s) e nenhum <script>; a interface ainda o exibe em iframe sandbox.
Os números vêm do `MetricsBundle` (código determinístico); frases como "1 em cada N" são calculadas aqui.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape
from markupsafe import Markup

from rota_segura.guardrails import BASE_SOURCE

_HTTP = re.compile(r"^https?://", re.I)

# Ícones SVG fixos (traço único, herdam a cor do texto), no lugar de glifos Unicode.
_SVG = '<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" ' \
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>'  # fmt: skip
_ICONS = {
    "ICON_WARN": Markup(_SVG.format('<path d="M8 1.8 14.8 14H1.2L8 1.8Z"/><path d="M8 6.2v3.4M8 11.8v.1"/>')),
    "ICON_UP": Markup(_SVG.format('<path d="M8 13V3M3.5 7.5 8 3l4.5 4.5"/>')),
    "ICON_DOWN": Markup(_SVG.format('<path d="M8 3v10M3.5 8.5 8 13l4.5-4.5"/>')),
}
_DIM_LABELS = {"faixa_etaria": "Faixa etária", "sexo": "Sexo", "tipo_envolvido": "Tipo de envolvido"}


def _br(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _safe_url(url: str) -> str:
    return url if _HTTP.match(url or "") else "#"


def _source_chips(sources: list[str]) -> list[tuple[str, str]]:
    return [("base", "BASE PRF") if s == BASE_SOURCE else ("news", f"NOTÍCIA {s.split(':', 1)[1]}") for s in sources]


_STATES = (("Óbito", "Mortes"), ("Lesões Graves", "Feridos graves"))
_AGE_ORDER = ["0-17", "18-29", "30-44", "45-59", "60+"]


def _profile_view(profile: dict[str, list[dict]]) -> list[dict]:
    """Agrupa o perfil por dimensão e situação, com largura de barra relativa ao maior valor numérico da coluna.

    Valores suprimidos ("<5", "suprimido") não ganham barra proporcional: nada que permita estimá-los.
    """
    view = []
    for dim, rows in profile.items():
        columns = []
        for state, title in _STATES:
            items = [r for r in rows if r["estado_fisico"] == state]
            if not items:
                continue
            if dim == "faixa_etaria":
                items.sort(key=lambda r: _AGE_ORDER.index(r["grupo"]) if r["grupo"] in _AGE_ORDER else 99)
            top = max((r["n"] for r in items if isinstance(r["n"], int)), default=0)
            columns.append({"title": title, "rows": [
                {
                    "group": r["grupo"],
                    "pct": round(100 * r["n"] / top, 1) if isinstance(r["n"], int) and top else None,
                    "text": str(r["n"]) if isinstance(r["n"], int) else ("<5" if r["n"] == "<5" else "oculto"),
                }
                for r in items
            ]})  # fmt: skip
        if columns:
            view.append({"label": _DIM_LABELS.get(dim, dim), "columns": columns})
    return view


def _one_in(pct: float) -> int | None:
    """Taxa em % -> "1 em cada N" (só quando fica legível)."""
    return round(100 / pct) if pct and pct >= 1 else None


TEMPLATE = """\
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório de segurança viária — {{ m.scope }}</title>
<style>
/* Tela: segue o tema do sistema (igual à interface). Impressão: sempre claro (economiza tinta). */
:root {
  color-scheme: dark;
  --ink: #e7eaeb; --ink-2: #b4bec3; --muted: #8c979d; --line: #2e373c; --surface: #14181b; --paper: #1c2226;
  --accent: #e8a317; --focus: #e8a317; --blue: #3987e5; --blue-bg: #17283b; --blue-ink: #9cc4f5;
  --good: #6cc28f; --good-bg: #1d3326; --bad: #f08a80; --bad-bg: #3d2220; --warn: #e9b44c; --warn-bg: #3a2f17;
  --bar-muted: #3b474d;
}
@media print, (prefers-color-scheme: light) {
  :root {
    color-scheme: light;
    --ink: #1d2327; --ink-2: #4f585e; --muted: #5c666d; --line: #dde1dc; --surface: #ffffff; --paper: #f6f7f4;
    --focus: #8a5a00; --blue: #2a78d6; --blue-bg: #e8f1fc; --blue-ink: #184f95;
    --good: #1f7a45; --good-bg: #e6f3eb; --bad: #b3261e; --bad-bg: #fbe9e7; --warn: #8a5a00; --warn-bg: #fbf1dd;
    --bar-muted: #c9cec8;
  }
}
@media print { :root { --ink: #0b0b0b; --paper: #ffffff; } }
.img-light { display: none !important; }
@media print, (prefers-color-scheme: light) {
  .img-dark { display: none !important; } .img-light { display: block !important; }
}
* { box-sizing: border-box; }
::selection { background: var(--accent); color: #1d2327; }
html { scrollbar-color: var(--bar-muted) var(--surface); }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 4px; }
.ico { width: 1em; height: 1em; flex: none; vertical-align: -0.14em; }
html { background: var(--surface); }
body { margin: 0 auto; max-width: 980px; padding: 28px 24px 48px; color: var(--ink);
  font: 15.5px/1.6 "Segoe UI", system-ui, -apple-system, Roboto, sans-serif; background: var(--surface); }
h1, h2, h3 { line-height: 1.25; margin: 0; }
p { margin: 0; }
a { color: inherit; text-decoration-color: var(--accent); text-underline-offset: 2px; }
header.top { border-bottom: 4px solid var(--accent); padding-bottom: 16px; margin-bottom: 20px; }
header.top h1 { font-size: 30px; margin: 0; text-wrap: balance; }
header.top h1 .scope { color: var(--accent); }
.byline { font-size: 14px; color: var(--ink-2); margin: 4px 0 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font-size: 13px; padding: 3px 10px; border-radius: 999px; background: var(--paper); border: 1px solid var(--line); }
.chip.warn { display: inline-flex; align-items: center; gap: 6px; background: var(--warn-bg); border-color: transparent; color: var(--warn); font-weight: 600; }
.notice { display: flex; gap: 8px; align-items: baseline; }
.notice .ico { color: var(--warn); }
.lead { font-size: 18px; line-height: 1.5; margin: 18px 0 6px; }
.notice { margin: 12px 0; padding: 10px 14px; border-radius: 10px; background: var(--warn-bg); font-size: 14px; }
section { margin-top: 34px; }
section > h2 { font-size: 21px; margin-bottom: 4px; }
section > .sub { color: var(--ink-2); margin-bottom: 14px; font-size: 14.5px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 18px; }
.kpi { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
.kpi .label { font-size: 13px; font-weight: 600; color: var(--ink-2); }
.kpi .value { font-size: 34px; font-weight: 700; letter-spacing: -.01em; margin: 2px 0 4px; font-variant-numeric: tabular-nums; }
.kpi .value small { font-size: 15px; font-weight: 600; color: var(--ink-2); margin-left: 2px; }
.kpi .read { font-size: 13.5px; color: var(--ink-2); line-height: 1.45; }
.trend { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; font-weight: 700; padding: 1px 8px; border-radius: 999px; margin-bottom: 4px; }
.trend.up { background: var(--bad-bg); color: var(--bad); }
.trend.down { background: var(--good-bg); color: var(--good); }
.trend.flat { background: var(--line); color: var(--ink-2); }
figure { margin: 0 0 14px; background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 10px; }
figure img { display: block; width: 100%; height: auto; }
figcaption { font-size: 13.5px; color: var(--ink-2); padding: 6px 6px 2px; }
.howto { background: var(--blue-bg); padding: 9px 13px; border-radius: 8px; max-width: 75ch;
  font-size: 13.5px; margin: 0 0 14px; }
.howto b { color: var(--ink); }
.route { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; margin-top: 18px; }
.route h2 { font-size: 17px; margin-bottom: 6px; }
.route ul { list-style: none; padding: 0; margin: 10px 0 0; display: grid; gap: 6px; }
.route li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 10px; border-radius: 8px; background: var(--surface); font-size: 14px; }
.profile { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.pcard { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
.pcard h3 { font-size: 15px; margin-bottom: 8px; }
.pcol + .pcol { margin-top: 12px; }
.pcol h4 { margin: 0 0 6px; font-size: 12.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); }
.prow { display: grid; grid-template-columns: minmax(80px, 34%) 1fr 64px; align-items: center; gap: 8px; font-size: 13.5px; margin: 4px 0; }
.ptrack { height: 10px; border-radius: 0 4px 4px 0; background: transparent; }
.pbar { height: 100%; border-radius: 0 4px 4px 0; background: var(--blue); min-width: 2px; }
.pbar.hidden-n { width: 26px; background: repeating-linear-gradient(45deg, var(--bar-muted) 0 4px, transparent 4px 8px); border-radius: 4px; }
.pval { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink); }
.pval.hidden-n { color: var(--muted); font-size: 12.5px; }
.route li span:last-child { color: var(--ink-2); white-space: nowrap; }
.insights h3 { font-size: 16px; margin: 18px 0 8px; }
.insights ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.insights li { background: var(--paper); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; }
.src { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 1px 7px; border-radius: 6px; margin-right: 6px; vertical-align: 1px; }
.src.base { background: var(--blue-bg); color: var(--blue-ink); }
.src.news { background: var(--warn-bg); color: var(--warn); }
.news { padding-left: 22px; margin: 0; }
.news li { margin: 6px 0; }
.news .meta { color: var(--muted); font-size: 13px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; background: var(--paper); }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
table.mini { font-size: 13px; margin-top: 6px; }
table.mini td, table.mini th { padding: 4px 8px; }
details { margin-top: 34px; background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 14px 18px; }
details summary { cursor: pointer; font-weight: 700; font-size: 16px; }
details h3 { font-size: 14.5px; margin: 14px 0 4px; }
details p, details li { font-size: 14px; color: var(--ink-2); }
details ul { padding-left: 20px; margin: 4px 0; }
code { font-family: ui-monospace, Consolas, monospace; font-size: .88em; }
footer { margin-top: 26px; color: var(--muted); font-size: 12.5px; }
@media print {
  html, body { background: #fff; color: #0b0b0b; }
  body { padding: 0; max-width: none; font-size: 12.5px; }
  .kpi, figure, .insights li, .route, .howto { break-inside: avoid; }
  section { break-inside: auto; }
  details { border: 0; padding: 0; }
  details > summary { list-style: none; }
  a { text-decoration: none; }
  @page { margin: 14mm; }
}
</style>
</head>
<body>
<header class="top">
  <h1>Segurança nas rodovias federais · <span class="scope">{{ m.scope }}</span></h1>
  <p class="byline">Rota Segura Analytics · base aberta da Polícia Rodoviária Federal</p>
  <div class="chips">
    <span class="chip">Período: <b>{{ m.period.label }}</b> ({{ m.period_days }} dias)</span>
    <span class="chip">Comparado com {{ m.previous_period.label }}</span>
    <span class="chip">Dado mais recente da PRF: {{ m.data_max_date.strftime('%d/%m/%Y') }}</span>
    {% if m.preliminary %}<span class="chip warn">{{ ICON_WARN }}Dados preliminares</span>{% endif %}
  </div>
  <p class="lead">{{ draft.headline }}</p>
  {% for w in warnings %}<p class="notice">{{ ICON_WARN }}<span>{{ w }}</span></p>{% endfor %}
</header>

<div class="kpis" role="list">
  <div class="kpi" role="listitem">
    <p class="label">Acidentes</p>
    <p class="value">{{ br(m.total_accidents, 0) }}</p>
    {% if m.variation_pct is not none %}
      {% set kind = "up" if m.variation_pct > 0 else "down" if m.variation_pct < 0 else "flat" %}
      <span class="trend {{ kind }}">{{ ICON_UP if kind == "up" else ICON_DOWN if kind == "down" else "=" }}{{ br(m.variation_pct|abs) }}% {{ "a mais" if kind == "up" else "a menos" if kind == "down" else "" }}</span>
    {% endif %}
    <p class="read">No período anterior foram {{ br(m.previous_total, 0) }}.</p>
  </div>
  <div class="kpi" role="listitem">
    <p class="label">Mortos</p>
    <p class="value">{{ br(m.deaths, 0) }}</p>
    <p class="read">{{ br(m.severe_injuries, 0) }} pessoas com ferimentos graves no mesmo período.</p>
  </div>
  <div class="kpi" role="listitem">
    <p class="label">Letalidade</p>
    <p class="value">{{ br(m.lethality_rate) }}<small>por 100</small></p>
    <p class="read">A cada 100 acidentes, cerca de {{ br(m.lethality_rate, 0) }} mortes.</p>
  </div>
  <div class="kpi" role="listitem">
    <p class="label">Gravidade</p>
    <p class="value">{{ br(m.severity_rate) }}<small>%</small></p>
    <p class="read">{% if one_in(m.severity_rate) %}Cerca de 1 em cada {{ one_in(m.severity_rate) }} acidentes teve ferido grave ou morte.{% else %}Acidentes com ferido grave ou morte.{% endif %}</p>
  </div>
</div>

{% if m.route %}
<div class="route">
  <h2>Rota analisada: {{ m.route.label }}</h2>
  <p>{{ br(m.route.distance_km) }} km de carro · rodovias federais no caminho:
    {% for b in m.route.brs %}<b>BR-{{ '%03d' % b }}</b>{{ ", " if not loop.last }}{% endfor %}.
    Os números acima consideram só estes trechos da base da PRF sobre o traçado:</p>
  <ul>
    {% for s in m.route.segments %}<li><span>{{ s.label }}</span><span>{{ s.accidents_matched }} acidentes no histórico</span></li>{% endfor %}
  </ul>
  {% if m.route.brs_without_data %}<p class="notice">Sem registros da PRF neste traçado:
    {% for b in m.route.brs_without_data %}BR-{{ '%03d' % b }}{{ ", " if not loop.last }}{% endfor %}
    (em geral, trecho sob gestão estadual). Rodovias estaduais e municipais não entram na base da PRF.</p>{% endif %}
</div>
{% endif %}

<section>
  <h2>Por que e onde acontecem</h2>
  <p class="sub">As causas registradas pela PRF e os trechos de 1 km com mais acidentes no período.</p>
  {% if charts.get("causes") %}<figure><img class="img-dark" src="{{ charts.causes_dark }}" alt="Barras: principais causas de acidentes e quantidade de cada uma"><img class="img-light" src="{{ charts.causes }}" alt="Barras: principais causas de acidentes e quantidade de cada uma">
    <table class="mini"><thead><tr><th>Causa</th><th class="num">Acidentes</th><th class="num">% do total</th><th class="num">Mortes</th></tr></thead><tbody>
    {% for c in m.top_causes %}<tr><td>{{ c.cause }}</td><td class="num">{{ c.accidents }}</td><td class="num">{{ br(c.share_pct) }}%</td><td class="num">{{ c.deaths }}</td></tr>{% endfor %}
    </tbody></table></figure>{% endif %}
  <p class="howto"><b>Como ler:</b> a causa é a que o policial registrou como principal na ocorrência. Um acidente tem uma causa principal na base.</p>
  {% if charts.get("segments") %}<figure><img class="img-dark" src="{{ charts.segments_dark }}" alt="Barras: trechos de rodovia com mais acidentes"><img class="img-light" src="{{ charts.segments }}" alt="Barras: trechos de rodovia com mais acidentes">
    <table class="mini"><thead><tr><th>Trecho</th><th class="num">Acidentes</th><th class="num">Mortes</th><th class="num">Graves ou fatais</th></tr></thead><tbody>
    {% for s in m.top_segments %}<tr><td>{{ s.label }}</td><td class="num">{{ s.accidents }}</td><td class="num">{{ s.deaths }}</td><td class="num">{{ s.severe_accidents }}</td></tr>{% endfor %}
    </tbody></table></figure>{% endif %}
  <p class="howto"><b>Como ler:</b> trecho é UF + BR + km inteiro (1 km de estrada). Empate é decidido por mortes e depois por acidentes graves.</p>
</section>

<section>
  <h2>Quando acontecem</h2>
  <p class="sub">Dia a dia no último mês disponível e mês a mês no último ano.</p>
  <figure><img class="img-dark" src="{{ charts.daily_dark }}" alt="Barras: acidentes por dia nos últimos 30 dias disponíveis"><img class="img-light" src="{{ charts.daily }}" alt="Barras: acidentes por dia nos últimos 30 dias disponíveis"></figure>
  <figure><img class="img-dark" src="{{ charts.monthly_dark }}" alt="Barras: acidentes por mês nos últimos 12 meses disponíveis"><img class="img-light" src="{{ charts.monthly }}" alt="Barras: acidentes por mês nos últimos 12 meses disponíveis"></figure>
</section>

{% if victim_profile %}
<section>
  <h2>Quem são as vítimas graves e fatais</h2>
  <p class="sub">Pessoas mortas ou com ferimentos graves no período, agrupadas e anonimizadas.</p>
  <div class="profile">
  {% for dim in profile_view(victim_profile) %}
    <div class="pcard">
      <h3>{{ dim.label }}</h3>
      {% for col in dim.columns %}
      <div class="pcol">
        <h4>{{ col.title }}</h4>
        {% for row in col.rows %}
        <div class="prow">
          <span>{{ row.group }}</span>
          <span class="ptrack">{% if row.pct is not none %}<span class="pbar" style="width: {{ row.pct }}%; display: block"></span>{% else %}<span class="pbar hidden-n" style="display: block"></span>{% endif %}</span>
          <span class="pval{{ ' hidden-n' if row.pct is none }}">{{ row.text }}</span>
        </div>
        {% endfor %}
      </div>
      {% endfor %}
    </div>
  {% endfor %}
  </div>
  <p class="howto" style="margin-top: 12px"><b>Como ler:</b> cada barra é o número de pessoas no grupo. Barra listrada = grupo pequeno demais para mostrar (<b>&lt;5</b>) ou <b>oculto</b> para não permitir descobrir o valor por subtração do total (LGPD).</p>
</section>
{% endif %}

<section class="insights">
  <h2>O que os dados dizem</h2>
  <p class="sub">Comentários escritos por IA e conferidos automaticamente contra os números da base.
    <span class="src base">BASE PRF</span> = dado oficial calculado ·
    <span class="src news">NOTÍCIA n</span> = contexto de notícia (não confirma causa).</p>
  {% for section in draft.sections %}
  <h3>{{ section.title }}</h3>
  <ul>
    {% for p in section.paragraphs %}<li>{% for kind, label in chips(p.sources) %}<span class="src {{ kind }}">{{ label }}</span>{% endfor %}{{ p.text }}</li>{% endfor %}
  </ul>
  {% endfor %}
</section>

<section>
  <h2>Notícias consultadas</h2>
  {% if news %}<ol class="news">
    {% for n in news %}<li><a href="{{ safe_url(n.url) }}" rel="noopener noreferrer" target="_blank">{{ n.title }}</a>
      <span class="meta">— {{ n.source }}{% if n.published %}, {{ n.published }}{% endif %}</span></li>{% endfor %}
  </ol>{% else %}<p class="sub">Nenhuma notícia relevante encontrada (ou busca desligada).</p>{% endif %}
</section>

<details>
  <summary>Como ler este relatório e de onde vêm os números</summary>
  <h3>Definições</h3>
  <ul>
    <li><b>Variação:</b> (acidentes no período − acidentes no período anterior) ÷ período anterior.</li>
    <li><b>Letalidade:</b> mortos por 100 acidentes. Não é porcentagem: um acidente pode ter mais de uma morte.</li>
    <li><b>Gravidade:</b> % de acidentes com pelo menos um ferido grave ou morto.</li>
    <li><b>Período:</b> últimos {{ m.period_days }} dias <i>disponíveis</i> na base. A PRF publica com ~1 mês de atraso, então o período não termina hoje.{% if m.route %} Na rota usamos {{ m.period_days }} dias porque em 30 dias um trajeto tem poucos acidentes.{% endif %}</li>
  </ul>
  <h3>Transparência</h3>
  <ul>
    <li>Execução <code>{{ run_id }}</code>: trilha de auditoria em <code>audit/{{ run_id }}.jsonl</code> e manifesto em <code>audit/{{ run_id }}.manifest.json</code>.</li>
    <li>Modelo de linguagem: <code>{{ model }}</code> · prompts versão <code>{{ prompt_version }}</code>.</li>
    <li>Checagem automática do texto: {{ "aprovado" if guard.passed else "reprovado (trechos removidos, ver avisos)" }} após {{ attempts }} tentativa(s).</li>
    <li>Todos os números, tabelas e gráficos vêm de código (SQL/DuckDB) sobre a base aberta da PRF. A IA só escreve os comentários e não pode citar número que não esteja na base.</li>
    <li>Notícias servem só de contexto; causa de acidente vem exclusivamente da base.</li>
    <li>Nenhum dado de pessoa vai para a IA: só agregados, com supressão de grupos pequenos (LGPD).</li>
    <li>Fonte: <a href="https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf" rel="noopener noreferrer" target="_blank">Dados Abertos da PRF</a>{% if m.route %} · traçado da rota: OpenStreetMap (Nominatim/OSRM){% endif %}.</li>
  </ul>
</details>

<footer>Gerado em {{ generated_at }} · Rota Segura Analytics (PoC)</footer>
</body>
</html>
"""


def render_html(
    *, metrics, draft, news, charts: dict[str, Path], victim_profile, warnings, run_id, model, prompt_version,
    guard, attempts, generated_at: str, out_dir: Path,
) -> Path:  # fmt: skip
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape(default_for_string=True))
    env.globals.update(
        br=_br, chips=_source_chips, safe_url=_safe_url, one_in=_one_in, profile_view=_profile_view, **_ICONS
    )
    html = env.from_string(TEMPLATE).render(
        m=metrics, draft=draft, news=news, charts={k: _data_uri(p) for k, p in charts.items()},
        victim_profile=victim_profile, warnings=warnings, run_id=run_id, model=model, prompt_version=prompt_version,
        guard=guard, attempts=attempts, generated_at=generated_at,
    )  # fmt: skip
    path = out_dir / "relatorio.html"
    path.write_text(html, encoding="utf-8")
    return path
