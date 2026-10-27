"""Métricas determinísticas sobre a base normalizada (DuckDB). O LLM nunca calcula números."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
from pydantic import BaseModel

from rota_segura.config import Settings, settings
from rota_segura.data.privacy import suppress_small_cells


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
    scope: str  # "Brasil" ou sigla da UF
    uf: str | None
    data_max_date: date
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

    def numbers(self) -> set[float]:
        """Todos os números citáveis pelo LLM (usado pelo guardrail de alucinação numérica)."""
        values: set[float] = {
            self.total_accidents, self.previous_total, self.deaths, self.severe_injuries,
            self.lethality_rate, self.severity_rate, self.data_max_date.year,
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

    def _where(self, uf: str | None) -> tuple[str, list]:
        return ("uf = ?", [uf]) if uf else ("TRUE", [])

    def compute(self, uf: str | None = None) -> MetricsBundle:
        where, params = self._where(uf)
        max_date = self.con.execute(f"SELECT max(data)::DATE FROM acidentes WHERE {where}", params).fetchone()[0]
        if max_date is None:
            raise ValueError(f"Sem dados para a UF {uf}.")
        days = self.cfg.period_days
        period = Period(start=max_date - timedelta(days=days - 1), end=max_date)
        previous = Period(start=period.start - timedelta(days=days), end=period.start - timedelta(days=1))

        current = self._summary(where, params, period)
        prev_total = self._summary(where, params, previous)["accidents"]
        variation = round(100 * (current["accidents"] - prev_total) / prev_total, 2) if prev_total else None

        return MetricsBundle(
            scope=uf or "Brasil",
            uf=uf,
            data_max_date=max_date,
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
            daily=self._daily(where, params, period),
            monthly=self._monthly(where, params, max_date),
            preliminary=bool(current["preliminary"]),
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


def _add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)
