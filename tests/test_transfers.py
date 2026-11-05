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


def test_free_transfer_used_for_a_clear_upgrade():
    projs, team_of = pool()
    start = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of)
    owned = _current(start)
    star = next(p for p in projs if p.position == "MID" and p.element not in owned and p.price <= 60)
    star.xp_by_gw = {9: 9.0, 10: 9.0}
    plan = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert [p.element for p in plan.bought] == [star.element] and len(plan.sold) == 1 and plan.hits == 0
    assert star.element in {p.element for p in plan.xi} and plan.bank_after >= 0


def test_hits_only_when_the_gain_beats_4_points():
    projs, team_of = pool()
    start = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of)
    owned = _current(start)
    outsiders = [p for p in projs if p.position == "MID" and p.element not in owned and p.price <= 60][:2]
    weakest_mid = min((p for p in start.xi if p.position == "MID"), key=lambda p: p.xp_by_gw[9])
    base = weakest_mid.xp_by_gw[9]
    # Slightly better than the weakest starter: worth a free transfer, never a hit.
    for p in outsiders:
        p.xp_by_gw = {9: base + 1.2, 10: base + 1.2}
    assert squad.pick_squad(projs, GWS, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=0).bought == []
    one = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert len(one.bought) == 1 and one.hits == 0
    # Much better: a second transfer with a 4-point hit is worth it.
    for p in outsiders:
        p.xp_by_gw = {9: base + 6.0, 10: base + 6.0}
    two = squad.pick_squad(projs, GWS, rules.DEFAULT, team_of, current=owned, bank=0, free_transfers=1)
    assert len(two.bought) == 2 and two.hits == 1
