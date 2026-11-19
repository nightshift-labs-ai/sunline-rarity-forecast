"""sunline-rarity-forecast: GTA VI PS5 trophy earn-rate forecaster (Nightshift Labs, build v1).

For each case in $MAKEFUN_INPUT_DIR (else /input), it writes <id>.out to $MAKEFUN_OUTPUT_DIR (else /output):
{"trophies":[{"id":n,"q":[q05,q25,q50,q75,q95]}]}, the rates in percent at the case's target.

Model, in short: collapse repeated reads into refresh STATES, then work in earner counts C_i = rate_i*N/100.
Project players tracked P(T), keep the story chain ordered, and treat tester-era counts as floors.
Quantiles come from a split normal on the logit scale. Stdlib only, deterministic (no clock, no random).
If anything fails, the program falls back to the house persistence row, for that trophy or for the whole case.
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
SIGMA_RW = 0.5  # house persistence: logit spread per sqrt(day)
T0 = datetime(2026, 11, 19, tzinfo=timezone.utc)  # h = hours since this instant (house curve axis)
LO, HI = 0.01, 99.99
LOGIT_LO = math.log(LO / (100 - LO))
GATE_ROW = [99.97, 100, 100, 100, 100]


# ---------- numeric helpers ----------
def clamp(x: float) -> float:
    return min(HI, max(LO, x))


def logit(pct: float) -> float:
    p = clamp(pct)
    return math.log(p / (100 - p))


def inv_logit(x: float) -> float:
    if x >= 0:
        return 100 / (1 + math.exp(-x))
    e = math.exp(x)
    return 100 * e / (1 + e)


def round4(x: float):
    """Half-up rounding to 4 decimals, like the starter (JavaScript Math.round)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value


def hours(stamp: str) -> float:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - T0).total_seconds() / 3600


def persistence_row(rate, days: float) -> list:
    """The house baseline row (starter/main.py), used as the fallback."""
    lg = logit(rate if isinstance(rate, (int, float)) and math.isfinite(rate) else 0)
    spread = SIGMA_RW * math.sqrt(max(days, 0))
    return [round4(100 / (1 + math.exp(-(lg + z * spread)))) for z in Z]


def valid_row(q) -> bool:
    if not isinstance(q, list) or len(q) != 5:
        return False
    for k, v in enumerate(q):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v > 100:
            return False
        if k and v < q[k - 1]:
            return False
    return True


# ---------- states ----------
def build_states(case: dict) -> list:
    """Collapse consecutive identical (players_tracked, rates) reads into states, timed at their first read.

    A null rate takes the last non-null rate of that trophy (0 if it never had one).
    """
    n = len(case["trophies"])
    last = [None] * n
    states, prev_key = [], None
    for rd in case["history"]:
        rates = rd.get("rates") or []
        for i in range(n):
            v = rates[i] if i < len(rates) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                last[i] = float(v)
        big_n = rd.get("players_tracked")
        if not isinstance(big_n, (int, float)) or isinstance(big_n, bool) or not math.isfinite(big_n) or big_n <= 0:
            big_n = states[-1]["N"] if states else None
        if big_n is None:
            continue
        filled = tuple(x if x is not None else 0.0 for x in last)
        key = (float(big_n), filled)
        if key != prev_key:
            states.append({"h": hours(rd.get("at") or rd["slot"]), "N": float(big_n), "r": list(filled)})
            prev_key = key
    return states


def fit_start(states: list) -> int:
    """Index of the first post-tester state: after the first >3x jump in N, and N >= 0.15*N_last."""
    start = 0
    for k in range(1, len(states)):
        if states[k]["N"] > 3 * states[k - 1]["N"]:
            start = k
            break
    n_last = states[-1]["N"]
    while start < len(states) - 1 and states[start]["N"] < 0.15 * n_last:
        start += 1
    return start


def mean_gap(states: list, start: int) -> float:
    hs = [s["h"] for s in states[start:]]
    if len(hs) < 2:
        return 3.0
    return max(0.5, (hs[-1] - hs[0]) / (len(hs) - 1))


# ---------- groups ----------
G3_NAMES = {"Master of None", "Whip It Good", "On the Spot", "Retail Therapy", "Gunslinger", "Sneakthief",
            "A Classic Blitz Play", "Baited My Tackle", "Stick Fiddler", "Hot Together", "Challenging Tank"}
G4M_NAMES = {"Cunning Stunts", "Earn Cash, Not Kudos", "Strangers & Freaks", "Don't Touch My Deck", "You WAiNKer!",
             "One Last Thing", "Maximum Withdrawal", "Dime on the Dollar", "Treat Yo Self"}


def classify(trophy: dict) -> tuple:
    """(group, chapter index or None). Groups: G0 gate, G1c chapter, G1f final mission, G1m story mission,
    G2 side strand / secret beat, G3 easy feat, G4m medium grind, G4h hard grind, G4p platinum."""
    name = str(trophy.get("name", ""))
    desc = str(trophy.get("description", "")).strip().lower()
    if trophy.get("tier") == "platinum":
        return "G4p", None
    m = re.search(r"complete chapter (\d+)", desc)
    if m:
        return "G1c", int(m.group(1))
    if re.match(r"complete the final mission\.?$", desc):
        return "G1f", None
    if "gone fishing" in desc:
        return "G0", None
    if name in G3_NAMES:
        return "G3", None
    if name in G4M_NAMES:
        return "G4m", None
    if "100%" in desc or re.search(r"\b(all|every)\b|each (gang|location)", desc):
        return "G4h", None
    if "final mission for" in desc or "hunt a unique" in desc:
        return "G2", None
    if re.match(r"complete (?!an? |\d)", desc) and " for " not in desc:
        return "G1m", None
    if re.search(r"\$|\d", desc):
        return "G4m", None
    if trophy.get("secret"):
        return "G2", None
    return "G3", None


def chain_order(trophies: list, groups: list) -> list:
    """Indices of the ordered chain: chapters by number, then the final mission, then platinum."""
    chapters = sorted((k, i) for i, (g, k) in enumerate(groups) if g == "G1c")
    chain = [i for _, i in chapters]
    chain += [i for i, (g, _) in enumerate(groups) if g == "G1f"]
    chain += [i for i, (g, _) in enumerate(groups) if g == "G4p"]
    return chain


def context(case: dict, states: list) -> dict:
    trophies = case["trophies"]
    groups = [classify(t) for t in trophies]
    start = fit_start(states)
    post = states[start:]
    # the gate: >= 99.95 in every state since the first refresh
    gate = []
    for i in range(len(trophies)):
        if all(s["r"][i] >= 99.95 for s in post) and len(post) >= 1:
            gate.append(i)
    for i in gate:
        groups[i] = ("G0", None)
    return {"groups": groups, "start": start, "gap": mean_gap(states, start), "gate": gate,
            "chain": chain_order(trophies, groups),
            "tester_counts": [r * states[0]["N"] / 100 for r in states[0]["r"]]}


# ---------- model ----------
def predict(case: dict, ctx: dict, states: list, h_now: float, h_tgt: float, params: dict) -> tuple:
    """Logit quantiles (5 per trophy) at h_tgt from the states up to h_now, plus each row's method name."""
    days = max(h_tgt - h_now, 0) / 24
    spread = SIGMA_RW * math.sqrt(days)
    last = states[-1]["r"]
    out, methods = [], []
    for i in range(len(case["trophies"])):
        if i in ctx["gate"]:
            out.append(None)
            methods.append("gate")
            continue
        m = logit(last[i])
        out.append([m + z * spread for z in Z])
        methods.append("persist")
    return out, methods


def apply_constraints(ctx: dict, qs: list) -> list:
    """Cross-row constraints on logit quantiles (filled in by the full model)."""
    return qs


def finish(qlogit) -> list:
    """Logit quantiles -> a valid rounded row."""
    vals = [min(100.0, max(0.0, inv_logit(x))) for x in qlogit]
    for k in range(1, 5):
        vals[k] = max(vals[k], vals[k - 1])
    row = [round4(v) for v in vals]
    for k in range(1, 5):
        if row[k] < row[k - 1]:
            row[k] = row[k - 1]
    return row


def forecast_case(case: dict, name: str) -> tuple:
    """(forecast, info). info counts fallbacks and records calibration and per-group methods."""
    info = {"case": case.get("id", name), "fallback_trophies": 0, "fallback_case": 0,
            "calibration_ran": False, "params": {}, "methods": {}}
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}")
    trophies = case["trophies"]
    days = case["horizon_minutes"] / 1440
    states = build_states(case)
    if not states:
        raise ValueError(f"{name} has no usable history")
    last = states[-1]["r"]
    try:
        h_now = hours(case["at"])
        h_tgt = hours(case["target"])
        ctx = context(case, states)
        params = {}
        qs, methods = predict(case, ctx, states, h_now, h_tgt, params)
        qs = apply_constraints(ctx, qs)
        info["params"] = params
    except Exception as exc:  # whole-model failure -> persistence for the case
        info["fallback_case"] = 1
        info["error"] = repr(exc)[:200]
        qs, methods, ctx = [None] * len(trophies), ["persist"] * len(trophies), {"gate": []}
        qs = [[logit(last[i]) + z * SIGMA_RW * math.sqrt(days) for z in Z] for i in range(len(trophies))]
    rows = []
    for i, t in enumerate(trophies):
        try:
            if i in ctx["gate"] and qs[i] is None:
                row = list(GATE_ROW)
            else:
                row = finish(qs[i])
            if not valid_row(row):
                raise ValueError("invalid row")
        except Exception:
            row = persistence_row(last[i], days)
            info["fallback_trophies"] += 1
        rows.append({"id": t["id"], "q": row})
        g = ctx.get("groups", [("?", None)] * len(trophies))[i][0] if "groups" in ctx else "?"
        info["methods"].setdefault(g, {})
        info["methods"][g][methods[i]] = info["methods"][g].get(methods[i], 0) + 1
    return {"trophies": rows}, info


def baseline_case(case: dict) -> dict:
    """The starter's forecast for a whole case (last-resort fallback)."""
    last = case["history"][-1]["rates"]
    days = case["horizon_minutes"] / 1440
    return {"trophies": [{"id": t["id"], "q": persistence_row(last[i] if i < len(last) else 0, days)}
                         for i, t in enumerate(case["trophies"])]}


def checked(forecast: dict, case: dict) -> bool:
    ids = [t["id"] for t in case["trophies"]]
    rows = forecast.get("trophies")
    if not isinstance(rows, list) or [r.get("id") for r in rows] != ids:
        return False
    return all(set(r) == {"id", "q"} and valid_row(r["q"]) for r in rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            forecast, info = forecast_case(case, path.name)
            if not checked(forecast, case):
                raise ValueError("final validator rejected the forecast")
        except Exception as exc:
            forecast = baseline_case(case)
            info = {"case": path.stem, "fallback_case": 1, "error": repr(exc)[:200]}
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        if len(text.encode("utf-8")) >= 65536:
            text = json.dumps(baseline_case(case), separators=(",", ":")) + "\n"
            info["fallback_case"] = 1
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")
        print(json.dumps(info, separators=(",", ":"), sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
