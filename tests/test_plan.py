from fplbot.model.project import PlayerProjection
from fplbot.plan import chips, rules, squad

GWS = [9, 10]


def proj(i, pos, team, price, xp, mins=90):
    return PlayerProjection(element=i, code=i, name=f"P{i}", team=f"T{team}", position=pos, price=price,
                            status="a", xp_by_gw={9: xp, 10: xp}, parts_next={}, minutes_next=mins)


def pool():
    ps, i = [], 0
    for pos, n in (("GKP", 6), ("DEF", 14), ("MID", 14), ("FWD", 9)):
        for k in range(n):
            i += 1
            ps.append((proj(i, pos, team=i % 10, price=40 + 5 * (k % 6), xp=2 + (k % 6) * 0.8), i % 10))
    # A star that every squad wants, and three cheap good players from one club to test the club limit.
    i += 1
    ps.append((proj(i, "FWD", 99, 150, 12.0), 99))
    for j in range(4):
        i += 1
        ps.append((proj(i, "MID", 77, 45, 6.0), 77))
    return [p for p, _ in ps], {p.element: t for p, t in ps}


def test_pick_squad_obeys_rules_and_picks_obvious_players():
    projs, team_of = pool()
    r = rules.DEFAULT
    plan = squad.pick_squad(projs, GWS, r, team_of)
    sq = [dict(element=p.element, position=p.position, team=team_of[p.element], price=p.price) for p in plan.squad]
    assert rules.validate(r, sq, [p.element for p in plan.xi], [p.element for p in plan.bench],
                          plan.captain.element, plan.vice.element) == []
    assert plan.captain.xp_by_gw[9] == 12.0
    assert sum(1 for p in plan.squad if team_of[p.element] == 77) == 3
    assert plan.bench[0].position == "GKP"


def test_validate_catches_breaches():
    r = rules.DEFAULT
    sq = [dict(element=i, position="MID", team=1, price=100) for i in range(15)]
    errs = rules.validate(r, sq, list(range(11)), list(range(11, 15)), 0, 0)
    joined = " ".join(errs)
    assert "needs 2 GKP" in joined and "max 3" in joined and "budget" in joined and "captain" in joined


def test_chip_rules():
    projs, team_of = pool()
    plan = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of)
    d = chips.decide(plan, {"bboost", "3xc", "freehit", "wildcard"}, first_gameweek=True)
    bench_total = sum(p.xp_by_gw[9] for p in plan.bench)
    assert (d.chip == "bboost") == (bench_total >= chips.BENCH_BOOST_THRESHOLD)
    assert any("Free Hit: not allowed" in line for line in d.lines)
    for p in plan.bench:
        p.xp_by_gw[9] = 0.5
    d2 = chips.decide(plan, {"bboost", "3xc"}, first_gameweek=True)
    assert d2.chip == "3xc"  # 12-point captain, best week ahead: Triple Captain qualifies
    d3 = chips.decide(plan, {"3xc"}, first_gameweek=False, best_later_captain=(13.5, 15))
    assert d3.chip is None   # a clearly better week (by more than 1 point) is coming in the chip window
    d3b = chips.decide(plan, {"3xc"}, first_gameweek=False, best_later_captain=(12.8, 15, "X"))
    assert d3b.chip == "3xc"  # a later week only slightly better: play now
    plan.captain.xp_by_gw[9] = 6.5
    d4 = chips.decide(plan, {"3xc"}, first_gameweek=False, best_later_captain=(6.0, 15))
    assert d4.chip is None and any("floor" in line for line in d4.lines)


def test_card_explains_every_player():
    from datetime import datetime, timezone
    from fplbot.plan import card
    projs, team_of = pool()
    for p in projs:
        p.fixtures_by_gw = {9: ["AAA (H)"], 10: ["BBB (A)"]}
        p.evidence = {"p_play": 0.9, "p60": 0.8, "mins_if_play": 85, "xg90": 0.3, "xa90": 0.1, "n_matches": 8}
        p.parts_next = {"appearance": 2.0, "goals": 1.0, "bonus": 0.4}
    plan = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of)
    d = chips.decide(plan, {"bboost"}, first_gameweek=True)
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    text = card.render(season="2026-27", gw=9, kind="draft", deadline=now, now=now, plan=plan, chip=d, all_projs=projs,
                       opponents={}, budget=1000, mode="test", model_version="x", data_note="test", team_name=None)
    assert "HOW THE SQUAD WAS BUILT" in text and "WHY EACH PLAYER" in text and "CLUBS IN THE SQUAD" in text
    assert "Value by position" in text
    for p in plan.squad:
        assert f"  {p.name} ({p.team}, {p.position}" in text
    assert text.count("Versus alternatives:") == 15
