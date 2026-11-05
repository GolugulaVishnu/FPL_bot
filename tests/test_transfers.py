from fplbot import team
from fplbot.plan import rules, squad

from .test_plan import GWS, pool


def test_selling_price():
    assert team.selling_price(75, 78) == 76   # rules page example: rise halved, rounded down
    assert team.selling_price(70, 75) == 72
    assert team.selling_price(50, 51) == 50
    assert team.selling_price(60, 57) == 57   # falls passed on in full


def test_free_transfers():
    assert team.free_transfers([{"event": 9, "event_transfers": 0}], []) == 1
    assert team.free_transfers([{"event": 9}, {"event": 10, "event_transfers": 0}], []) == 2
    assert team.free_transfers([{"event": 9}, {"event": 10, "event_transfers": 1}], []) == 1
    assert team.free_transfers([{"event": 9}, {"event": 10, "event_transfers": 3}], []) == 1
    rows = [{"event": 9}] + [{"event": g, "event_transfers": 0} for g in range(10, 20)]
    assert team.free_transfers(rows, []) == 5
    assert team.free_transfers([{"event": 9}, {"event": 10, "event_transfers": 8}], [("wildcard", 10)]) == 1


def test_chips_available():
    st = team.TeamState(1, 9, [], 11, 1, [("bboost", 9)], {})
    chips = [{"name": "bboost", "start_event": 1, "stop_event": 19}, {"name": "bboost", "start_event": 20, "stop_event": 38},
             {"name": "3xc", "start_event": 1, "stop_event": 19}]
    assert st.chips_available(chips, 10) == {"3xc"}
    assert st.chips_available(chips, 20) == {"bboost"}


def _current(plan):
    return {p.element: p.price for p in plan.squad}


def test_injured_starter_covered_from_bench_keeps_free_transfer():
    """Owner's rule: an injury is covered from the bench first; a bench-only replacement isn't worth a transfer."""
    projs, team_of = pool()
    start = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of)
    victim = next(p for p in start.xi if p.position == "MID" and p.xp_by_gw[9] < 12)
    victim.xp_by_gw = {9: 0.0, 10: 0.0}
    plan = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of, current=_current(start), bank=0, free_transfers=1)
    assert plan.bought == [] and victim.element not in {p.element for p in plan.xi}


G3 = [9, 10, 11]


def pool3():
    projs, team_of = pool()
    for p in projs:
        p.xp_by_gw = {g: p.xp_by_gw[9] for g in G3}
    return projs, team_of


def _setall(p, xp):
    p.xp_by_gw = {g: xp for g in G3}


def test_transfer_needs_10_point_gain_over_horizon():
    projs, team_of = pool3()
    start = squad.pick_squad(projs, G3, rules.DEFAULT, team_of)
    owned = _current(start)
    weakest = min((p for p in start.xi if p.position == "MID"), key=lambda p: p.xp_by_gw[9])
    star = next(p for p in projs if p.position == "MID" and p.element not in owned and p.price <= weakest.price)
    _setall(star, weakest.xp_by_gw[9] + 2.5)       # +7.5 over 3 weeks: below the bar, save the transfer
    assert squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1).bought == []
    _setall(star, weakest.xp_by_gw[9] + 4.0)       # +12 over 3 weeks: over the bar
    plan = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert [p.element for p in plan.bought] == [star.element] and plan.hits == 0


def test_long_term_injury_replaced_even_for_a_small_gain():
    projs, team_of = pool3()
    start = squad.pick_squad(projs, G3, rules.DEFAULT, team_of)
    owned = _current(start)
    victim = min((p for p in start.squad if p.position == "MID"), key=lambda p: p.xp_by_gw[9])
    _setall(victim, 0.0)
    victim.status = "i"
    plan = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert [p.element for p in plan.sold] == [victim.element] and len(plan.bought) == 1 and plan.hits == 0


def test_incoming_players_must_be_fit():
    projs, team_of = pool3()
    start = squad.pick_squad(projs, G3, rules.DEFAULT, team_of)
    owned = _current(start)
    weakest = min((p for p in start.xi if p.position == "MID"), key=lambda p: p.xp_by_gw[9])
    star = next(p for p in projs if p.position == "MID" and p.element not in owned and p.price <= weakest.price)
    _setall(star, weakest.xp_by_gw[9] + 6.0)
    star.status = "d"
    plan = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert star.element not in {p.element for p in plan.bought}


def test_hit_needs_the_bar_plus_4():
    projs, team_of = pool3()
    start = squad.pick_squad(projs, G3, rules.DEFAULT, team_of)
    owned = _current(start)
    xi_mids = sorted((p for p in start.xi if p.position == "MID"), key=lambda p: p.xp_by_gw[9])[:2]
    outs = [p for p in projs if p.position == "MID" and p.element not in owned and p.price <= min(m.price for m in xi_mids)][:2]
    for o, m in zip(outs, xi_mids):
        _setall(o, m.xp_by_gw[9] + 4.0)            # +12 each: one free transfer yes, a hit no (needs 14+)
    one = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert len(one.bought) == 1 and one.hits == 0
    for o, m in zip(outs, xi_mids):
        _setall(o, m.xp_by_gw[9] + 6.0)            # +18 each: worth the hit
    two = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert len(two.bought) == 2 and two.hits == 1


def test_second_opinion_overrides_only_when_clearly_better():
    from fplbot.plan import card
    projs, team_of = pool3()
    start = squad.pick_squad(projs, G3, rules.DEFAULT, team_of)
    owned = _current(start)
    weakest = min((p for p in start.xi if p.position == "MID"), key=lambda p: p.xp_by_gw[9])
    star = next(p for p in projs if p.position == "MID" and p.element not in owned and p.price <= weakest.price)
    _setall(star, weakest.xp_by_gw[9] + 3.0)    # +9 over 3 weeks: under the owner's 10-point bar
    rule = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    alt = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1,
                           gain_bar=squad.FT_VALUE)
    assert rule.bought == [] and [p.element for p in alt.bought] == [star.element]
    lines = " ".join(card.second_opinion_lines(rule, alt))
    assert "OVERRIDES YOUR GUIDANCE" in lines      # ~+5 weighted after the 2-point FT value: over the 3-point margin
    _setall(star, weakest.xp_by_gw[9] + 1.2)    # small gain: rules stand
    alt2 = squad.pick_squad(projs, G3, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1,
                            gain_bar=squad.FT_VALUE)
    assert "your rules stand" in " ".join(card.second_opinion_lines(rule, alt2)) or alt2.bought == []
