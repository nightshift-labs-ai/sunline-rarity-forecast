"""Local scorer + backtest (plumbing/timing/crash test; the synthetic data encodes our own assumptions).

python3 tools/backtest.py [--case FILE] [--worst] [--write]
  no --case: build a synthetic f00-like history from the kit's launch-night reads (in memory; --write -> synth/).
  Cuts the history at checkpoints, runs main.forecast_case in-process, scores pinball on the logit scale
  (RULES Scoring), and prints ours / house persistence / house curve per group and in total, plus 90% coverage.
"""
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import main as M  # noqa: E402

KIT_IN = Path("/home/agent/makefun-kit/gta6-trophy-rarity-forecast-01/x_s260/x/gta6-trophy-rarity-forecast-01-kit/input")


def item_loss(y: float, q: float, tau: float) -> float:
    d = M.logit(y) - M.logit(q)
    return 2 * max(tau * d, (tau - 1) * d)


def score(rows: list, ys: list) -> float:
    tot = [item_loss(y, q, tau) for r, y in zip(rows, ys) for q, tau in zip(r, M.LEVELS)]
    return sum(tot) / len(tot)


def worked_example() -> float:
    return round(score([[10, 15, 20, 25, 35]] * 2, [22, 8]), 6)


def house_curve(case: dict) -> list:
    """House curve: per-trophy LS line of logit(rate) vs ln(1+h) over the last 24 h of reads, read at the target."""
    hist, days = case["history"], case["horizon_minutes"] / 1440
    h_at, h_t = M.hours(case["at"]), M.hours(case["target"])
    win = [r for r in hist if M.hours(r["at"]) >= h_at - 24]
    rows = []
    for i in range(len(case["trophies"])):
        pts = [(math.log(1 + M.hours(r["at"])), M.logit(r["rates"][i])) for r in win if r["rates"][i] is not None]
        if len(pts) < 3:
            rows.append(M.persistence_row(hist[-1]["rates"][i], days))
            continue
        n = len(pts)
        mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx > 0 else 0.0
        a = my - b * mx
        res = math.sqrt(sum((p[1] - a - b * p[0]) ** 2 for p in pts) / max(n - 2, 1))
        s = math.sqrt((M.SIGMA_RW * math.sqrt(days)) ** 2 + res ** 2)
        m = a + b * math.log(1 + h_t)
        rows.append([M.round4(M.inv_logit(m + z * s)) for z in M.Z])
    return rows


def iso(h: float) -> str:
    return (M.T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def synth(worst: bool = False, seed: int = 7) -> dict:
    """f00-like history: launch-night reads, then refreshes every 2-4 h, N x~11 by the deadline, cohort earning."""
    base = json.loads((KIT_IN / "p01.in").read_text())
    rng, tro = random.Random(seed), base["trophies"]
    r0 = base["history"][0]["rates"]
    tester = [r * 638 / 100 for r in r0]
    prof = []  # (share p, delay h, time-constant h) per trophy, by group
    for t in tro:
        g, k = M.classify(t)
        p = {"G0": (1, 0, .1), "G1c": (.97 - .12 * (k or 1), 4 + 9 * (k or 1), 6), "G1f": (.45, 48, 15), "G1m": (.6, 0, 0),
             "G2": (.4, 10, 25), "G3": (.55, 1, 10), "G4m": (.12, 20, 60), "G4h": (.01, 60, 80), "G4p": (.003, 90, 50)}[g]
        if g == "G1m":
            j = rng.randint(1, 4)
            p = (.97 - .12 * j - .05, 6 + 9 * j, 6)
        prof.append((p[0] * rng.uniform(.85, 1.1), p[1] * rng.uniform(.8, 1.2), p[2]))

    def big_n(h):
        return 638 if h < 4.5 else 3868 * ((1 + h) / 5.5) ** 1.0

    def counts(h):
        c, s = list(tester), 4.5
        while s < h:
            dn = big_n(s + 1) - big_n(s) if s > 4.5 else big_n(5.5) - 638
            for i, (p, d, tc) in enumerate(prof):
                a = h - s - d
                if a > 0:
                    c[i] += dn * p * (1 - math.exp(-a / tc))
            s += 1
        return c

    reads, h, nxt, state = [], -1 / 6, 4.5, None
    while h < 169.2:
        if state is None or h >= nxt or (worst and h <= 59.5):
            n = big_n(h) + (h * 6 if worst else 0)
            c = counts(h)
            state = (int(n), [min(100.0, round(100 * ci / n, 2)) if g[0] != "G0" else 100.0
                              for ci, g in zip(c, map(M.classify, tro))])
            if h >= nxt:
                nxt = h + rng.uniform(2, 4)
        reads.append({"slot": iso(round(h * 6) / 6), "at": iso(h), "players_tracked": state[0],
                      "trophies_earned": 0, "rates": list(state[1])})
        h += 1 / 6
    return {"schema": base["schema"], "id": "s00", "levels": M.LEVELS, "game": base["game"], "trophies": tro,
            "history": reads, "notes": "synthetic"}


def cut(full: dict, h_at: float, horizon_h: float) -> tuple:
    hist = [r for r in full["history"] if M.hours(r["at"]) < h_at]
    tgt = h_at + horizon_h
    later = [r for r in full["history"] if tgt <= M.hours(r["slot"]) < tgt + 1]
    if not later:
        return None, None
    case = dict(full, history=hist, at=iso(h_at), target=iso(tgt), horizon_minutes=round(horizon_h * 60))
    return case, later[0]["rates"]


def run(full: dict, checkpoints: list, horizon_h: float) -> None:
    groups = [M.classify(t)[0] for t in full["trophies"]]
    agg = {}
    for c in checkpoints:
        case, ys = cut(full, c, horizon_h)
        if case is None:
            print(f"checkpoint h={c}: no answer read in the history, skipped")
            continue
        t0 = time.perf_counter()
        fc, info = M.forecast_case(case, "cut")
        dt = time.perf_counter() - t0
        print(f"checkpoint h={c}: {len(case['history'])} reads, run {dt:.3f}s, fallbacks "
              f"{info.get('fallback_trophies')}/{info.get('fallback_case')}, calibration_ran={info.get('calibration_ran')}")
        meth = {"ours": [r["q"] for r in fc["trophies"]], "persist": M.__dict__["baseline_case"](case)["trophies"],
                "curve": house_curve(case)}
        meth["persist"] = [r["q"] for r in meth["persist"]]
        for name, rows in meth.items():
            for g, r, y in zip(groups, rows, ys):
                for key in (g, "TOTAL"):
                    a = agg.setdefault((name, key), [0.0, 0, 0])
                    a[0] += score([r], [y])
                    a[1] += 1
                    a[2] += r[0] <= y <= r[4]
    keys = sorted({k for _, k in agg}, key=lambda k: (k == "TOTAL", k))
    print(f"{'group':6} {'n':>4} {'ours':>9} {'persist':>9} {'curve':>9} {'cov90 ours':>11}")
    for k in keys:
        o, p, cv = agg[("ours", k)], agg[("persist", k)], agg[("curve", k)]
        print(f"{k:6} {o[1]:4d} {o[0] / o[1]:9.6f} {p[0] / p[1]:9.6f} {cv[0] / cv[1]:9.6f} {o[2] / o[1]:11.2f}")


def main() -> None:
    args = sys.argv[1:]
    print(f"RULES worked example: {worked_example()} (expected 0.403404)")
    if "--case" in args:
        full = json.loads(Path(args[args.index("--case") + 1]).read_text())
    else:
        full = synth(worst="--worst" in args)
        if "--write" in args:  # f00-like cut cases (deadline 59.5 h, target +108.5 h) for running main.py itself
            (ROOT / "synth").mkdir(exist_ok=True)
            for worst, name in ((False, "s00"), (True, "s01w")):
                case, _ = cut(synth(worst=worst), 59.5, 108.5)
                (ROOT / "synth" / f"{name}.in").write_text(json.dumps(case))
    distinct = len({(r["players_tracked"], tuple(r["rates"])) for r in full["history"]})
    print(f"history: {len(full['history'])} reads, {distinct} distinct")
    run(full, [35.5, 47.5, 59.5], 108.5)


if __name__ == "__main__":
    main()
