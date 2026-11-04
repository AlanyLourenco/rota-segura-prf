"""Métricas determinísticas sobre a base normalizada (DuckDB). O LLM nunca calcula números."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel

from rota_segura.config import Settings, settings
from rota_segura.data.privacy import suppress_small_cells
from rota_segura.route import RouteInfo, RouteSegment

GRID_DEG = 0.01  # célula de ~1,1 km para associar acidentes georreferenciados ao traçado da rota
SEGMENT_GAP_KM = 5  # kms de uma mesma BR mais distantes que isso viram trechos separados
KM_SLACK = 1  # folga (km) de cada lado ao limitar um trecho à distância percorrida na BR
MIN_ANCHORS = 3  # mínimo de acidentes para um intervalo de km contar como trecho da rota


class Period(BaseModel):
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.start:%d/%m/%Y} a {self.end:%d/%m/%Y}"


class CauseRank(BaseModel):
    cause: str
    accidents: int
    deaths: int
    share_pct: float


class SegmentRank(BaseModel):
    uf: str
    br: int
    km: int
    accidents: int
    deaths: int
    severe_accidents: int

    @property
    def label(self) -> str:
        return f"{self.uf} · BR-{self.br:03d} · km {self.km}"


class DailyPoint(BaseModel):
    day: date
    accidents: int


class MonthlyPoint(BaseModel):
    month: str  # YYYY-MM
    accidents: int
    deaths: int


class MetricsBundle(BaseModel):
    scope: str  # "Brasil", sigla da UF ou "Rota A → B"
    uf: str | None
    data_max_date: date
    period_days: int
    period: Period
    previous_period: Period
    total_accidents: int
    previous_total: int
    variation_pct: float | None
    deaths: int
    severe_injuries: int
    lethality_rate: float
    severity_rate: float
    top_causes: list[CauseRank]
    top_segments: list[SegmentRank]
    daily: list[DailyPoint]
    monthly: list[MonthlyPoint]
    preliminary: bool
    route: RouteInfo | None = None

    def numbers(self) -> set[float]:
        """Todos os números citáveis pelo LLM (usado pelo guardrail de alucinação numérica)."""
        values: set[float] = {
            self.total_accidents, self.previous_total, self.deaths, self.severe_injuries,
            self.lethality_rate, self.severity_rate, self.data_max_date.year, self.period_days,
            self.period.start.year, self.previous_period.start.year,
            self.period.start.day, self.period.end.day, self.previous_period.start.day, self.previous_period.end.day,
            self.period.start.month, self.period.end.month,
            self.previous_period.start.month, self.previous_period.end.month,
        }  # fmt: skip
        if self.variation_pct is not None:
            values |= {self.variation_pct, abs(self.variation_pct)}
        for c in self.top_causes:
            values |= {c.accidents, c.deaths, c.share_pct}
        for s in self.top_segments:
            values |= {s.br, s.km, s.accidents, s.deaths, s.severe_accidents}
        values |= {p.accidents for p in self.daily} | {m.accidents for m in self.monthly}
        values |= {m.deaths for m in self.monthly}
        if self.route:
            values |= {self.route.distance_km, *self.route.brs}
            for seg in self.route.segments:
                values |= {seg.br, seg.km_start, seg.km_end}
        for m in self.monthly:  # "2025-09" -> 2025 e 9 são citáveis
            year, month = m.month.split("-")
            values |= {int(year), int(month)}
        return {float(v) for v in values}


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 2) if whole else 0.0


class MetricsEngine:
    """Executa as consultas sobre o Parquet normalizado."""

    def __init__(self, parquet: Path | None = None, cfg: Settings = settings) -> None:
        self.cfg = cfg
        path = parquet or cfg.occurrences_parquet
        if not Path(path).exists():
            raise FileNotFoundError(f"{path} não encontrado. Rode `rota-segura ingest` antes.")
        self.con = duckdb.connect()
        self.con.execute(f"CREATE VIEW acidentes AS SELECT * FROM read_parquet('{Path(path).as_posix()}')")

    def victim_profile(self, uf: str | None, period: Period) -> dict[str, list[dict]] | None:
        """Perfil agregado de vítimas graves/fatais no período (marginais, com supressão de células)."""
        people = self.cfg.people_parquet
        if not people.exists():
            return None
        where, params = self._where(uf)
        profile = {}
        for dim in ("faixa_etaria", "sexo", "tipo_envolvido"):
            rows = self.con.execute(
                f"""
                SELECT estado_fisico, {dim} AS grupo, sum(n)::INT AS n
                FROM read_parquet('{people.as_posix()}')
                WHERE {where} AND data BETWEEN ? AND ? AND estado_fisico IN ('Óbito', 'Lesões Graves')
                GROUP BY 1, 2 ORDER BY 1, n DESC
                """,
                [*params, period.start, period.end],
            ).fetchall()
            records = [{"estado_fisico": e, "grupo": g, "n": n} for e, g, n in rows]
            profile[dim] = suppress_small_cells(records, self.cfg.min_cell_size)
        return profile

    def route_segments(
        self, br_paths: dict[int, list[list[tuple[float, float]]]], br_km: dict[int, float] | None = None
    ) -> list[RouteSegment]:
        """Trechos (UF + BR + intervalo de km) da base que ficam sobre o traçado da rota.

        Para cada BR, densifica só os pedaços do traçado percorridos nela, marca as células de ~1,1 km que eles
        tocam (e as vizinhas) e pega os acidentes georreferenciados daquela BR nessas células; os kms viram
        intervalos por UF+BR. Intervalos ancorados por menos de `MIN_ANCHORS` acidentes são descartados
        (coordenada errada na base não deve virar trecho da rota). Como a coordenada da base é imprecisa em área
        urbana, um trecho nunca passa da distância percorrida na BR (`br_km`) + folga, centrado na mediana.
        """
        cells = [(br, cy, cx) for br, paths in br_paths.items() for cy, cx in _route_cells(paths)]
        if not cells:
            return []
        self.con.register("route_cells", pd.DataFrame(cells, columns=["br", "cy", "cx"]))
        try:
            rows = self.con.execute(
                f"""
                SELECT a.uf, a.br, floor(a.km)::INT AS km, count(*) AS n
                FROM acidentes a JOIN route_cells c
                  ON a.br = c.br
                 AND floor(a.latitude / {GRID_DEG})::INT = c.cy AND floor(a.longitude / {GRID_DEG})::INT = c.cx
                WHERE a.km IS NOT NULL
                GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
                """
            ).fetchall()
        finally:
            self.con.unregister("route_cells")
        groups: list[list[tuple[str, int, int, int]]] = []
        for row in rows:
            last = groups[-1][-1] if groups else None
            if last and last[:2] == row[:2] and row[2] - last[2] <= SEGMENT_GAP_KM:
                groups[-1].append(row)
            else:
                groups.append([row])
        segments = []
        for group in groups:
            uf, br = group[0][:2]
            kms = [km for _, _, km, n in group for _ in range(n)]
            start, end = kms[0], kms[-1]
            limit = (br_km or {}).get(br)
            if limit is not None and end - start > 1.5 * limit + 2 * KM_SLACK:  # só corrige desvio grosseiro
                mid = kms[len(kms) // 2]
                half = math.ceil(limit / 2 + KM_SLACK)
                start, end = max(start, mid - half), min(end, mid + half)
            n = sum(1 for km in kms if start <= km <= end)
            if n >= MIN_ANCHORS:
                segments.append(RouteSegment(uf=uf, br=br, km_start=start, km_end=end, accidents_matched=n))
        return segments

    def _where(self, uf: str | None, segments: list[RouteSegment] | None = None) -> tuple[str, list]:
        if segments:
            clause = " OR ".join(["(uf = ? AND br = ? AND km >= ? AND km < ?)"] * len(segments))
            return f"({clause})", [v for s in segments for v in (s.uf, s.br, s.km_start, s.km_end + 1)]
        return ("uf = ?", [uf]) if uf else ("TRUE", [])

    def compute(self, uf: str | None = None, route: RouteInfo | None = None) -> MetricsBundle:
        where, params = self._where(uf, route.segments if route else None)
        max_date = self.con.execute(f"SELECT max(data)::DATE FROM acidentes WHERE {where}", params).fetchone()[0]
        if max_date is None:
            raise ValueError(f"Sem dados para o escopo {route.label if route else uf}.")
        days = self.cfg.route_period_days if route else self.cfg.period_days
        period = Period(start=max_date - timedelta(days=days - 1), end=max_date)
        previous = Period(start=period.start - timedelta(days=days), end=period.start - timedelta(days=1))

        current = self._summary(where, params, period)
        prev_total = self._summary(where, params, previous)["accidents"]
        variation = round(100 * (current["accidents"] - prev_total) / prev_total, 2) if prev_total else None

        daily_start = max_date - timedelta(days=self.cfg.period_days - 1)  # gráfico diário: sempre 30 dias
        return MetricsBundle(
            scope=f"Rota {route.label}" if route else uf or "Brasil",
            uf=uf,
            data_max_date=max_date,
            period_days=days,
            period=period,
            previous_period=previous,
            total_accidents=current["accidents"],
            previous_total=prev_total,
            variation_pct=variation,
            deaths=current["deaths"],
            severe_injuries=current["severe_injuries"],
            lethality_rate=_pct(current["deaths"], current["accidents"]),
            severity_rate=_pct(current["severe_accidents"], current["accidents"]),
            top_causes=self._top_causes(where, params, period, current["accidents"]),
            top_segments=self._top_segments(where, params, period),
            daily=self._daily(where, params, Period(start=daily_start, end=max_date)),
            monthly=self._monthly(where, params, max_date),
            preliminary=bool(current["preliminary"]),
            route=route,
        )

    def _summary(self, where: str, params: list, period: Period) -> dict:
        row = self.con.execute(
            f"""
            SELECT count(*), coalesce(sum(mortos), 0), coalesce(sum(feridos_graves), 0),
                   count(*) FILTER (WHERE mortos > 0 OR feridos_graves > 0),
                   coalesce(bool_or(preliminar), false)
            FROM acidentes WHERE {where} AND data BETWEEN ? AND ?
            """,
            [*params, period.start, period.end],
        ).fetchone()
        keys = ("accidents", "deaths", "severe_injuries", "severe_accidents", "preliminary")
        return dict(zip(keys, row, strict=True))

    def _top_causes(self, where: str, params: list, period: Period, total: int) -> list[CauseRank]:
        rows = self.con.execute(
            f"""
            SELECT causa_acidente, count(*) AS n, sum(mortos)
            FROM acidentes WHERE {where} AND data BETWEEN ? AND ?
            GROUP BY 1 ORDER BY n DESC, 1 LIMIT ?
            """,
            [*params, period.start, period.end, self.cfg.top_n],
        ).fetchall()
        return [CauseRank(cause=c, accidents=n, deaths=d, share_pct=_pct(n, total)) for c, n, d in rows]

    def _top_segments(self, where: str, params: list, period: Period) -> list[SegmentRank]:
        # Trecho = UF + BR + km inteiro. Critério: nº de acidentes; desempate por mortos e graves.
        rows = self.con.execute(
            f"""
            SELECT uf, br, floor(km)::INT AS km_int, count(*) AS n, sum(mortos) AS m,
                   count(*) FILTER (WHERE mortos > 0 OR feridos_graves > 0) AS g
            FROM acidentes
            WHERE {where} AND data BETWEEN ? AND ? AND br IS NOT NULL AND km IS NOT NULL
            GROUP BY 1, 2, 3 ORDER BY n DESC, m DESC, g DESC, 1, 2, 3 LIMIT ?
            """,
            [*params, period.start, period.end, self.cfg.top_n],
        ).fetchall()
        return [SegmentRank(uf=u, br=b, km=k, accidents=n, deaths=m, severe_accidents=g) for u, b, k, n, m, g in rows]

    def _daily(self, where: str, params: list, period: Period) -> list[DailyPoint]:
        rows = self.con.execute(
            f"""
            SELECT d::DATE, count(a.data)
            FROM range(?::TIMESTAMP, ?::TIMESTAMP + INTERVAL 1 DAY, INTERVAL 1 DAY) t(d)
            LEFT JOIN (SELECT data FROM acidentes WHERE {where}) a ON a.data = t.d
            GROUP BY 1 ORDER BY 1
            """,
            [period.start, period.end, *params],
        ).fetchall()
        return [DailyPoint(day=d, accidents=n) for d, n in rows]

    def _monthly(self, where: str, params: list, max_date: date) -> list[MonthlyPoint]:
        # Últimos 12 meses completos ou parciais terminando no mês da data máxima disponível.
        last_month = max_date.replace(day=1)
        first_month = _add_months(last_month, -(self.cfg.monthly_window - 1))
        rows = self.con.execute(
            f"""
            SELECT strftime(date_trunc('month', data), '%Y-%m') AS m, count(*), sum(mortos)
            FROM acidentes WHERE {where} AND data >= ? AND data <= ?
            GROUP BY 1 ORDER BY 1
            """,
            [*params, first_month, max_date],
        ).fetchall()
        return [MonthlyPoint(month=m, accidents=n, deaths=d) for m, n, d in rows]


def _route_cells(paths: list[list[tuple[float, float]]]) -> set[tuple[int, int]]:
    """Células da grade tocadas pelos pedaços do traçado (densificados) e suas 8 vizinhas."""
    cells: set[tuple[int, int]] = set()
    for path in paths:
        for (lat1, lon1), (lat2, lon2) in zip(path, path[1:] or path, strict=False):
            steps = max(1, math.ceil(max(abs(lat2 - lat1), abs(lon2 - lon1)) / (GRID_DEG / 2)))
            for i in range(steps + 1):
                lat, lon = lat1 + (lat2 - lat1) * i / steps, lon1 + (lon2 - lon1) * i / steps
                cy, cx = math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG)
                cells.update((cy + dy, cx + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1))
    return cells


def _add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)
