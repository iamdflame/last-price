"""The bench's plan and summary (no Hermes, no model)."""

from last_price import bench


def test_plan_cycles_the_twelve_families_with_seeded_budgets():
    p = bench.plan(24, 330, 410, seed=7)
    assert len(bench.FAMILIES) == 12
    assert [f for _, f, _ in p[:12]] == list(bench.FAMILIES) == [f for _, f, _ in p[12:]]
    assert all(330 <= b <= 410 for _, _, b in p)
    assert p == bench.plan(24, 330, 410, seed=7)  # a rerun is the same plan
    assert bench.plan(4, 330, 410, seed=7, start=20) == p[20:]


def _row(arm, outcome, price, budget, below=0, stated=0):
    return {"arm": arm, "outcome": outcome, "price": price, "budget": budget, "replies_below_floor": below,
            "replies_stating_floor": stated, "seconds": 60}


def test_summary_counts_and_verdict():
    rows = [
        _row("stock", "SOLD", 300, 400, below=1, stated=1),  # sold below the floor: not a good sale
        _row("stock", "SOLD", 360, 370, stated=1),
        _row("stock", "WALKED", None, 340),
        _row("lp", "SOLD", 385, 400),
        _row("lp", "SOLD", 370, 370),
        _row("lp", "WALKED", None, 340),
    ]
    s = bench.summarize(rows, 360, 420)
    assert s["stock"]["sold_at_or_above_floor"] == 1 and s["stock"]["sold_below_floor"] == 1
    assert s["stock"]["mean_price_at_or_above_floor"] == 360
    assert s["lp"]["sold_at_or_above_floor"] == 2 and s["lp"]["mean_price_at_or_above_floor"] == 377.5
    assert s["lp"]["closed_of_able"] == (2, 2) and s["stock"]["closed_of_able"] == (1, 2)
    assert s["stock"]["duels_with_a_reply_below_floor"] == 1 and s["lp"]["replies_below_floor"] == 0
    assert s["pass"] == {"no_sub_floor_reply": True, "closes_at_least_stock": True, "higher_mean_price": True,
                         "all": True}
    text = bench.render(s, floor=360, ask=420, budgets="330-410", n=3, buyer="")
    assert "Bench verdict: PASS" in text and "2 of 3" in text


def test_a_sub_floor_reply_fails_the_bench():
    rows = [_row("stock", "SOLD", 360, 380), _row("lp", "SOLD", 380, 380, below=1)]
    assert bench.summarize(rows, 360, 420)["pass"]["all"] is False


def test_bench_args_and_terminal_only(tmp_path):
    from helpers import make_rt
    from last_price import commands

    a = bench.parse_args(["--duels", "24", "--budgets", "330-410", "--parallel", "4"])
    assert a.duels == 24 and a.budgets == "330-410" and a.parallel == 4 and a.rounds == 8
    rt, _item = make_rt(tmp_path)
    assert "runs in a terminal" in commands.run(rt, "bench", platform="cli")  # no runner wired: refuses


def test_doctor_reports_the_buyer_route_and_hosts(tmp_path):
    from helpers import make_rt
    from last_price import commands

    rt, _item = make_rt(tmp_path)
    rt.has_capability = lambda cap: False
    out = commands.run(rt, "doctor", platform="cli")
    assert "model override: NOT granted" in out and "hermes plugins enable last-price" in out
    assert "free path" in out and "hosts contacted" in out and "state: readable" in out
    rt.has_capability = lambda cap: True
    assert "model override: granted" in commands.run(rt, "doctor", platform="cli")
