"""Busca de notícias recentes (Tavily se configurado; senão RSS públicos).

Conteúdo de notícia é dado NÃO confiável: é limpo, truncado, tem PII mascarada e entra no prompt
delimitado, nunca como instrução.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import httpx
from pydantic import BaseModel

from rota_segura.guardrails import redact_pii

log = logging.getLogger(__name__)

TOPICS = ("acidente rodovia federal", "operação PRF", "feriado prolongado rodovias", "obras rodovia BR")
AGENCIA_GOV_RSS = "https://agenciagov.ebc.com.br/noticias/RSS"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
TAVILY_URL = "https://api.tavily.com/search"
_RELEVANT = re.compile(r"\b(PRF|rodovi\w*|BR-?\d{2,3}|acidente\w*|tr[aâ]nsito|feriado|estrada\w*)\b", re.I)
_UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}  # fmt: skip


class NewsItem(BaseModel):
    id: int
    title: str
    source: str
    url: str
    published: str | None
    snippet: str
    provider: str


def _clean(text: str, limit: int = 400) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return redact_pii(text)[:limit]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _queries(uf: str | None) -> list[str]:
    place = _UF_NAMES.get(uf, "") if uf else ""
    return [f"{topic} {place}".strip() for topic in TOPICS]


def _from_tavily(queries: list[str], api_key: str, days: int) -> list[dict]:
    items: list[dict] = []
    with httpx.Client(timeout=30) as client:
        for q in queries:
            resp = client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": q, "topic": "news", "days": days, "max_results": 5, "country": "brazil"},
            )
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                items.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": httpx.URL(r.get("url", "")).host,
                        "published": r.get("published_date"),
                        "snippet": r.get("content", ""),
                        "provider": "tavily",
                    }
                )
    return items


def _from_rss(queries: list[str]) -> list[dict]:
    items: list[dict] = []
    feeds = [(GOOGLE_NEWS_RSS.format(q=quote_plus(q)), "google_news_rss") for q in queries]
    feeds.append((AGENCIA_GOV_RSS, "agencia_gov_rss"))
    for url, provider in feeds:
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "rota-segura/0.1"})
            feed = feedparser.parse(resp.content)
        except httpx.HTTPError as exc:
            log.warning("RSS indisponível %s: %s", url, exc)
            continue
        limit = 3 if provider == "google_news_rss" else 30  # equilibra os temas
        for e in feed.entries[:limit]:
            text = f"{e.get('title', '')} {e.get('summary', '')}"
            if provider == "agencia_gov_rss" and not _RELEVANT.search(text):
                continue
            source = e.get("source", {}).get("title") if provider == "google_news_rss" else "Agência Gov"
            items.append(
                {
                    "title": e.get("title", ""),
                    "url": e.get("link", ""),
                    "source": source or provider,
                    "published": e.get("published") or e.get("updated"),
                    "snippet": e.get("summary", ""),
                    "provider": provider,
                }
            )
    return items


class NewsSnapshotError(ValueError):
    pass


def save_news(items: list[NewsItem], path: Path) -> str:
    """Grava o snapshot das notícias usadas na execução (reprodutibilidade) e devolve seu sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"items": [n.model_dump() for n in items]}, ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_news(path: Path) -> list[NewsItem]:
    """Lê um snapshot gravado por `save_news` (replay sem rede)."""
    try:
        return [NewsItem.model_validate(n) for n in json.loads(path.read_text(encoding="utf-8"))["items"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NewsSnapshotError(f"Snapshot de notícias inválido ({path}): {exc}") from exc


def search_news(uf: str | None, api_key: str | None = None, max_items: int = 8, days: int = 45) -> list[NewsItem]:
    """Busca notícias recentes, deduplica, filtra por data e devolve no máximo `max_items`."""
    queries = _queries(uf)
    try:
        raw = _from_tavily(queries, api_key, days) if api_key else _from_rss(queries)
    except httpx.HTTPError as exc:
        log.warning("Tavily falhou (%s); usando RSS.", exc)
        raw = _from_rss(queries)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen: set[str] = set()
    selected: list[NewsItem] = []
    for item in raw:
        key = re.sub(r"\W+", "", item["title"].lower())[:80]
        published = _parse_date(item["published"])
        if not key or key in seen or (published and published < cutoff):
            continue
        seen.add(key)
        selected.append(NewsItem(
            id=len(selected) + 1, title=_clean(item["title"], 200), source=_clean(item["source"] or "", 80),
            url=item["url"], published=published.date().isoformat() if published else None,
            snippet=_clean(item["snippet"]), provider=item["provider"],
        ))  # fmt: skip
        if len(selected) >= max_items:
            break
    return selected
