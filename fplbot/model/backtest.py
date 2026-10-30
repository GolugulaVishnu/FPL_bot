"""Walk-forward backtest on a finished season.

For each gameweek, the model is fitted only on data from before it (plus the
previous season), then its projections are compared with the points players
actually scored. Two benchmarks run on the same players:
- recent form: average points over the player's last 5 team fixtures
- FPL's own projection (the archive's xP column), where the archive has it

Past seasons have no injury or suspension flags, so the model can't see who
is ruled out; FPL's projection can. That handicap is reported, not hidden.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..datastore import DataStore
from ..scoring import normalise
from .xp import build_state, project_fixture

FORM_WINDOW = 5


@dataclass
class Scores:
    n: int = 0
    abs_err: float = 0.0
    sq_err: float = 0.0
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)

    def add(self, pred: float, actual: float) -> None:
        self.n += 1
        self.abs_err += abs(pred - actual)
        self.sq_err += (pred - actual) ** 2
        self.xs.append(pred)
        self.ys.append(actual)

    @property
    def mae(self) -> float:
        return self.abs_err / self.n if self.n else float("nan")

    @property
    def rmse(self) -> float:
        return math.sqrt(self.sq_err / self.n) if self.n else float("nan")

    @property
    def corr(self) -> float:
        n = len(self.xs)
        if n < 3:
            return float("nan")
        mx, my = sum(self.xs) / n, sum(self.ys) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(self.xs, self.ys))
        sxx = sum((x - mx) ** 2 for x in self.xs)
        syy = sum((y - my) ** 2 for y in self.ys)
        return sxy / math.sqrt(sxx * syy) if sxx and syy else float("nan")


@dataclass
class BacktestResult:
    season: str
    gws: list[int]
    model: Scores = field(default_factory=Scores)
    form: Scores = field(default_factory=Scores)
    # Same rows as `fpl`, so the comparison is like for like.
    model_vs_fpl: Scores = field(default_factory=Scores)
    fpl: Scores = field(default_factory=Scores)
    by_position: dict[str, Scores] = field(default_factory=dict)
    captain_model: list[float] = field(default_factory=list)
    captain_form: list[float] = field(default_factory=list)
    captain_fpl: list[float] = field(default_factory=list)
    captain_model_fpl_gws: list[float] = field(default_factory=list)  # model's captain, same gameweeks as captain_fpl
    top11_model: list[float] = field(default_factory=list)
    top11_form: list[float] = field(default_factory=list)
    best11: list[float] = field(default_factory=list)


def run(store: DataStore, season: str, prior_season: str | None, start_gw: int = 2, end_gw: int = 38,
        scoring: dict | None = None) -> BacktestResult:
    pts = normalise(scoring)
    res = BacktestResult(season, [])
    all_rows = store.matches(season)
    max_gw = max((r.gw for r in all_rows), default=0)

    for gw in range(start_gw, min(end_gw, max_gw) + 1):
        target = [r for r in all_rows if r.gw == gw]
        if not target:
            continue
        state = build_state(store, season, gw, prior_season)
        history: dict[int, list] = {}
        for r in all_rows:
            if r.gw < gw:
                history.setdefault(r.code, []).append(r)

        per_player: dict[int, dict] = {}
        for r in target:
            prof = state.profiles.get(r.code)
            if prof is None or not history.get(r.code):
                continue  # first appearance this season: nothing fair to predict from
            tc, oc = state.team_code.get(r.team), state.team_code.get(r.opponent)
            if tc is None or oc is None:
                continue
            p = project_fixture(prof, tc, oc, r.home, state.ratings, pts)
            d = per_player.setdefault(r.code, {"pred": 0.0, "actual": 0, "fpl": None, "pos": r.position})
            d["pred"] += p.xp
            d["actual"] += r.points
            if r.fpl_xp is not None:
                d["fpl"] = (d["fpl"] or 0.0) + r.fpl_xp
        if not per_player:
            continue
        res.gws.append(gw)

        for code, d in per_player.items():
            last = history[code][-FORM_WINDOW:]
            d["form"] = sum(x.points for x in last) / len(last)
            res.model.add(d["pred"], d["actual"])
            res.form.add(d["form"], d["actual"])
            res.by_position.setdefault(d["pos"], Scores()).add(d["pred"], d["actual"])
            if d["fpl"] is not None:
                res.model_vs_fpl.add(d["pred"], d["actual"])
                res.fpl.add(d["fpl"], d["actual"])

        ranked = list(per_player.values())
        res.captain_model.append(max(ranked, key=lambda d: d["pred"])["actual"])
        res.captain_form.append(max(ranked, key=lambda d: d["form"])["actual"])
        with_fpl = [d for d in ranked if d["fpl"] is not None]
        if with_fpl:
            res.captain_fpl.append(max(with_fpl, key=lambda d: d["fpl"])["actual"])
            res.captain_model_fpl_gws.append(res.captain_model[-1])
        res.top11_model.append(sum(d["actual"] for d in sorted(ranked, key=lambda d: -d["pred"])[:11]) / 11)
        res.top11_form.append(sum(d["actual"] for d in sorted(ranked, key=lambda d: -d["form"])[:11]) / 11)
        res.best11.append(sum(d["actual"] for d in sorted(ranked, key=lambda d: -d["actual"])[:11]) / 11)
    return res


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def report(res: BacktestResult) -> str:
    lines = [
        f"Backtest {res.season}, gameweeks {res.gws[0]}-{res.gws[-1]} ({len(res.gws)} gameweeks), "
        f"{res.model.n} player-gameweeks",
        "",
        "Accuracy per player per gameweek (lower error and higher correlation are better)",
        f"  {'':<28}{'MAE':>7}{'RMSE':>7}{'corr':>7}{'rows':>8}",
        f"  {'Model':<28}{res.model.mae:7.2f}{res.model.rmse:7.2f}{res.model.corr:7.3f}{res.model.n:8}",
        f"  {'Recent form (last 5)':<28}{res.form.mae:7.2f}{res.form.rmse:7.2f}{res.form.corr:7.3f}{res.form.n:8}",
    ]
    if res.fpl.n:
        lines += [
            "",
            "Where the archive has FPL's own projection (same rows for both):",
            f"  {'Model':<28}{res.model_vs_fpl.mae:7.2f}{res.model_vs_fpl.rmse:7.2f}{res.model_vs_fpl.corr:7.3f}{res.model_vs_fpl.n:8}",
            f"  {'FPL projection':<28}{res.fpl.mae:7.2f}{res.fpl.rmse:7.2f}{res.fpl.corr:7.3f}{res.fpl.n:8}",
            "  Note: FPL's projection knows about injuries and suspensions; this backtest's model does not.",
        ]
    lines += ["", "By position (model)"]
    for pos in ("GKP", "DEF", "MID", "FWD"):
        s = res.by_position.get(pos)
        if s:
            lines.append(f"  {pos:<28}{s.mae:7.2f}{s.rmse:7.2f}{s.corr:7.3f}{s.n:8}")
    lines += [
        "",
        "Picks (average actual points per gameweek)",
        f"  Captain = model's top player:        {_avg(res.captain_model):5.2f}",
        f"  Captain = best recent form:          {_avg(res.captain_form):5.2f}",
    ]
    if res.captain_fpl:
        lines.append(f"  Same {len(res.captain_fpl)} gameweeks where FPL's projection exists:")
        lines.append(f"    Captain = FPL projection's top:    {_avg(res.captain_fpl):5.2f}")
        lines.append(f"    Captain = model's top player:      {_avg(res.captain_model_fpl_gws):5.2f}")
    lines += [
        f"  Model's top 11, per player:          {_avg(res.top11_model):5.2f}",
        f"  Recent form's top 11, per player:    {_avg(res.top11_form):5.2f}",
        f"  Best possible 11 (hindsight):        {_avg(res.best11):5.2f}",
        "",
        "Top-11 picks ignore price, squad rules and position limits; they test ranking only.",
    ]
    return "\n".join(lines)
