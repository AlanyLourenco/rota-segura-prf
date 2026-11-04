"""Rota origem → destino (R10): geocodificação (Nominatim) + traçado de carro (OSRM), ambos do OpenStreetMap.

Só os nomes das cidades saem para o serviço de mapas. A associação do traçado com a base da PRF é feita
localmente e de forma determinística em `MetricsEngine.route_segments`.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
from pydantic import BaseModel

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{a};{b}"
USER_AGENT = "rota-segura-prf/0.1 (PoC educacional; github.com/AlanyLourenco/rota-segura-prf)"
_BR_REF = re.compile(r"\bBR[-\s]?(\d{2,3})\b", re.I)


class RouteError(Exception):
    """Falha ao traçar a rota (cidade não encontrada, serviço fora do ar)."""


class Place(BaseModel):
    query: str
    name: str
    uf: str | None
    lat: float
    lon: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.uf})" if self.uf else self.name


class RouteSegment(BaseModel):
    uf: str
    br: int
    km_start: int
    km_end: int
    accidents_matched: int  # acidentes da base (todo o histórico) que ancoraram o trecho no traçado

    @property
    def label(self) -> str:
        return f"{self.uf} · BR-{self.br:03d} · km {self.km_start}–{self.km_end}"


class RoutePlan(BaseModel):
    origin: Place
    destination: Place
    distance_km: float
    brs: list[int]  # rodovias federais citadas nos passos do OSRM, na ordem do trajeto
    # BR -> trechos do traçado (lista de (lat, lon)) percorridos nela. Fica local, nunca vai ao LLM.
    br_paths: dict[int, list[list[tuple[float, float]]]]
    br_km: dict[int, float]  # distância percorrida em cada BR (limita o tamanho dos trechos associados)

    @property
    def label(self) -> str:
        return f"{self.origin.label} → {self.destination.label}"


class RouteInfo(BaseModel):
    """O que vai para métricas, relatório, manifesto e LLM (sem a geometria)."""

    origin: str
    destination: str
    distance_km: float
    brs: list[int]
    segments: list[RouteSegment]

    @property
    def brs_without_data(self) -> list[int]:
        """BRs do traçado sem nenhum trecho na base da PRF (ex.: trechos sob gestão estadual)."""
        covered = {s.br for s in self.segments}
        return [br for br in self.brs if br not in covered]

    @property
    def label(self) -> str:
        return f"{self.origin} → {self.destination}"


def brs_from_refs(refs: list[str]) -> list[int]:
    seen: list[int] = []
    for ref in refs:
        for num in _BR_REF.findall(ref or ""):
            if int(num) not in seen:
                seen.append(int(num))
    return seen


def _geocode(client: httpx.Client, query: str) -> Place:
    params = {"q": query, "countrycodes": "br", "format": "jsonv2", "limit": 1, "addressdetails": 1}
    results = client.get(NOMINATIM_URL, params=params).raise_for_status().json()
    if not results:
        raise RouteError(f"Cidade não encontrada: {query!r}.")
    hit = results[0]
    address = hit.get("address", {})
    iso = address.get("ISO3166-2-lvl4", "")  # "BR-GO"
    name = address.get("city") or address.get("town") or address.get("village") or hit["display_name"].split(",")[0]
    return Place(
        query=query, name=name, uf=iso.split("-")[-1] if iso.startswith("BR-") else None,
        lat=float(hit["lat"]), lon=float(hit["lon"]),
    )  # fmt: skip


def plan_route(origin: str, destination: str, timeout: float = 30) -> RoutePlan:
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            a, b = _geocode(client, origin), _geocode(client, destination)
            url = OSRM_URL.format(a=f"{a.lon},{a.lat}", b=f"{b.lon},{b.lat}")
            data = client.get(url, params={"overview": "full", "geometries": "geojson", "steps": "true"}).json()
    except httpx.HTTPError as exc:
        raise RouteError(f"Serviço de rotas indisponível: {exc}") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError(f"Não foi possível traçar a rota de carro ({data.get('code')}).")
    route = data["routes"][0]
    br_paths: dict[int, list[list[tuple[float, float]]]] = {}
    br_km: dict[int, float] = {}
    for step in (step for leg in route["legs"] for step in leg["steps"]):
        path = [(lat, lon) for lon, lat in step["geometry"]["coordinates"]]
        for br in brs_from_refs([step.get("ref", "")]):
            br_paths.setdefault(br, []).append(path)
            br_km[br] = round(br_km.get(br, 0) + step["distance"] / 1000, 1)
    return RoutePlan(
        origin=a, destination=b, distance_km=round(route["distance"] / 1000, 1), brs=list(br_paths), br_paths=br_paths,
        br_km=br_km,
    )  # fmt: skip


Router = Callable[[str, str], RoutePlan]
