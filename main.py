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
    chain = chain_order(trophies, groups)
    story = [i for i in chain if groups[i][0] in ("G1c", "G1f")]
    return {"groups": groups, "start": start, "gap": mean_gap(states, start), "gate": gate,
            "chain": chain, "story": story,
            "final": [i for i in story if groups[i][0] == "G1f"],
            "plat": [i for i in chain if groups[i][0] == "G4p"],
            "missions": [i for i, (g, _) in enumerate(groups) if g == "G1m"],
            "hundred": [i for i, t in enumerate(trophies) if "100%" in str(t.get("description", ""))
                        and groups[i][0] == "G4h"],
            "tester_counts": [r * states[0]["N"] / 100 for r in states[0]["r"]]}


# ---------- model ----------
# M1 slope damping per group (prior), M2 flow factor f_g, prior logit spread at the 108 h horizon.
D_G = {"G1c": 0.6, "G1f": 0.6, "G1m": 0.6, "G2": 0.7, "G3": 0.6, "G4m": 0.9, "G4h": 0.9, "G4p": 0.9, "G0": 0.6}
F_G = {"G1c_early": 0.6, "G1c": 1.0, "G1f": 1.3, "G1m": 0.8, "G2": 0.8, "G3": 0.6, "G4m": 1.0, "G4h": 1.0,
       "G4p": 1.0, "G0": 0.6}
S_G = {"G1c_early": 0.35, "G1c": 0.8, "G1f": 0.8, "G1m": 0.6, "G2": 0.6, "G3": 0.45, "G4m": 0.9, "G4h": 0.9,
       "G4p": 0.9, "G0": 0.45}
PRIORS = {"damp": 1.0, "fmult": 1.0, "smult": 1.0, "skew": 1.0}
H_REF = 108.5  # the final's horizon, where S_G applies


def ls_fit(xs: list, ys: list) -> tuple:
    """(slope, residual sd) of a least-squares line."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return 0.0, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = math.sqrt(sum((y - my - b * (x - mx)) ** 2 for x, y in zip(xs, ys)) / max(n - 2, 1))
    return b, res


def thin(states: list, cap: int = 60) -> list:
    """At most ~cap states: every k-th plus the last (deterministic)."""
    if len(states) <= cap:
        return states
    k = -(-len(states) // cap)
    out = states[::k]
    if out[-1] is not states[-1]:
        out.append(states[-1])
    return out


def ref_state(post: list, h_last: float, back: float = 24.0) -> dict:
    ref = post[0]
    for s in post:
        if s["h"] <= h_last - back:
            ref = s
    return ref


def lnx(h: float) -> float:
    return math.log(1 + max(h, -0.9))


def project_p(post: list, h_last: float, t_eff: float) -> tuple:
    """(P(T), sigma_lnP): damped ln N vs ln(1+h) trend, geometric mean with the damped 24 h velocity."""
    n_last = post[-1]["N"]
    if len(post) < 2 or t_eff <= h_last:
        return n_last, 0.15
    win = thin([s for s in post if s["h"] >= h_last - 36])
    if len(win) < 2:
        win = post[-2:]
    b, _ = ls_fit([lnx(s["h"]) for s in win], [math.log(s["N"]) for s in win])
    lp1 = math.log(n_last) + max(0.0, b) * 0.8 * (lnx(t_eff) - lnx(h_last))
    ref = ref_state(post, h_last)
    dt = h_last - ref["h"]
    v = (n_last - ref["N"]) / dt if dt >= 1 else 0.0
    lp2 = math.log(n_last + max(v, 0.0) * (t_eff - h_last) * 0.7)
    lp = max(math.log(n_last), 0.5 * (lp1 + lp2))
    return math.exp(lp), min(0.4, 0.1 + abs(lp1 - lp2) / 2)


def pav_dec(vals: list) -> list:
    """Isotonic regression, non-increasing (pool adjacent violators)."""
    blocks = []
    for v in vals:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    out = []
    for s, c in blocks:
        out += [s / c] * c
    return out


def chain_closure(ctx, c_now, c_ref, n_now, n_ref, dt, h_last, t_eff, p_t) -> dict:
    """M3: integrate dC_k/dt = lambda_k (C_parent - C_k) hourly down the story chain; returns rates at t_eff."""
    tester = ctx["tester_counts"]
    story, missions = ctx["story"], ctx["missions"]
    parent = {}
    for pos, k in enumerate(story):
        parent[k] = story[pos - 1] if pos else None
    chapters = [k for k in story if ctx["groups"][k][0] == "G1c"]
    for m in missions:  # the chapter whose count is just above the mission's
        above = [k for k in chapters if c_now[k] >= c_now[m]]
        parent[m] = min(above, key=lambda k: (c_now[k], k)) if above else None
    rows = story + missions
    lam, strong = {}, []
    for k in rows:
        p = parent[k]
        par_now = n_now if p is None else c_now[p]
        par_ref = n_ref if p is None else c_ref[p]
        gap = 0.5 * ((par_now - c_now[k]) + (par_ref - c_ref[k]))
        gain = c_now[k] - c_ref[k]
        lam[k] = max(0.0, gain / (dt * max(gap, 1.0))) if dt >= 1 else 0.0
        if gain > 3 * tester[k] and lam[k] > 0:
            strong.append(lam[k])
    if strong:
        strong.sort()
        floor = 0.5 * strong[len(strong) // 2]
        for k in rows:
            lam[k] = max(lam[k], floor)
    for k in rows:
        lam[k] = min(lam[k], 0.5)
    span = t_eff - h_last
    steps = max(1, int(math.ceil(span)))
    step = span / steps
    c = {k: c_now[k] for k in rows}
    lp0, lp1 = math.log(n_now), math.log(p_t)
    for j in range(1, steps + 1):
        pt = math.exp(lp0 + (lp1 - lp0) * j / steps)
        for k in rows:  # story rows first (in order), then missions with updated parents
            p = parent[k]
            par = pt if p is None else c[p]
            if par > c[k]:
                c[k] += lam[k] * (par - c[k]) * step
    return {k: 100 * c[k] / p_t for k in rows}


def medians(case: dict, ctx: dict, states: list, h_now: float, h_tgt: float, params: dict) -> dict:
    """Median logits at the target and the facts the spreads need."""
    n = len(case["trophies"])
    start = fit_start(states)
    post = states[start:]
    last = states[-1]
    h_last = last["h"]
    gap = mean_gap(states, start)
    t_eff = max(h_now, h_tgt - gap / 2) if len(post) >= 2 else h_tgt
    p_t, sig_p = project_p(post, h_last, t_eff)
    c_now = [r * last["N"] / 100 for r in last["r"]]
    ref = ref_state(post, h_last)
    dt = h_last - ref["h"]
    c_ref = [r * ref["N"] / 100 for r in ref["r"]]
    tester = ctx["tester_counts"]
    win = thin([s for s in post if s["h"] >= h_last - 36])
    xs = [lnx(s["h"]) for s in win]
    dx = lnx(t_eff) - lnx(h_last)
    span = max(t_eff - h_last, 0.0)
    m3 = {}
    if len(post) >= 2 and dt >= 1 and span > 0:
        m3 = chain_closure(ctx, c_now, c_ref, last["N"], ref["N"], dt, h_last, t_eff, p_t)
    med, grp, ct, meth = [0.0] * n, [""] * n, [1.0] * n, [""] * n
    for i in range(n):
        g, k = ctx["groups"][i]
        gain = c_now[i] - c_ref[i]
        if dt >= 12 and g == "G4h" and gain > 2 * tester[i] + 2:
            g = "G4m"  # promoted: real growth
        if dt >= 12 and g == "G3" and c_now[i] <= 1.2 * tester[i] + 1:
            g = "G4h"  # demoted: still at the tester floor
        key = "G1c_early" if g == "G1c" and (k or 1) <= 2 else g
        grp[i] = key
        m_last = logit(last["r"][i])
        if len(post) < 2 or dt < 1 or span <= 0:
            med[i], ct[i], meth[i] = m_last, max(c_now[i], 1.0), "persist"
            continue
        if len(win) >= 3:
            b, _ = ls_fit(xs, [logit(s["r"][i]) for s in win])
            d = min(1.3, D_G.get(g, 0.7) * params["damp"])
            m1 = m_last + d * b * dx
        else:
            m1 = m_last
        v = max(0.0, gain / dt)
        c_t = min(c_now[i] + v * span * F_G.get(key, 1.0) * params["fmult"], 0.9999 * p_t)
        m2 = logit(100 * c_t / p_t)
        if i in m3:
            med[i] = 0.25 * m1 + 0.25 * m2 + 0.5 * logit(m3[i])
            meth[i] = "m123"
        else:
            med[i] = 0.4 * m1 + 0.6 * m2
            meth[i] = "m12"
        med[i] = max(med[i], logit(100 * 0.98 * c_now[i] / p_t))  # count floor
        ct[i] = max(inv_logit(med[i]) * p_t / 100, 1.0)
    chain = [i for i in ctx["chain"] if i not in ctx["gate"]]
    for i, v in zip(chain, pav_dec([med[i] for i in chain])):
        med[i] = v
    return {"med": med, "grp": grp, "ct": ct, "meth": meth, "sig_p": sig_p, "p_t": p_t, "span": span,
            "last": [logit(r) for r in last["r"]], "c_now": c_now, "post": len(post)}


def phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# Split-normal skew (s_lo, s_hi multipliers): late chain / grind fat upside, early chain and common rows fat downside.
SKEW_UP = {"G1c", "G1f", "G1m", "G2", "G4m", "G4h", "G4p"}


def predict(case: dict, ctx: dict, states: list, h_now: float, h_tgt: float, params: dict, mm=None) -> tuple:
    """Logit quantiles (5 per trophy) at h_tgt from the states up to h_now, plus each row's method name."""
    if mm is None:
        mm = medians(case, ctx, states, h_now, h_tgt, params)
    horizon = max(h_tgt - h_now, 0.0)
    diag = {"p_t": round(mm["p_t"], 1), "sig_p": round(mm["sig_p"], 3), "wide": 0, "sanity": 0}
    out, methods = [], []
    for i in range(len(case["trophies"])):
        if i in ctx["gate"]:
            out.append(None)
            methods.append("gate")
            continue
        g, med, last = mm["grp"][i], mm["med"][i], mm["last"][i]
        meth = mm["meth"][i]
        s_model = S_G.get(g, 0.7) * math.sqrt(horizon / H_REF)
        s = math.sqrt(s_model ** 2 + mm["sig_p"] ** 2 + 1 / mm["ct"][i]) * params["smult"]
        s = max(s, 0.15)
        # sanity: an absurd jump is pulled halfway back to the last rate and widened
        up_rare = med > last and g[:2] in ("G1", "G2") and inv_logit(last) < 1.0
        if abs(med - last) > 4 and not up_rare:
            med, s = 0.5 * (med + last), s * 1.5
            meth += "+sanity"
            diag["sanity"] += 1
        if s > 1.3:
            diag["wide"] += 1
        sk = params["skew"]
        if g in SKEW_UP:
            s_lo, s_hi = s * 0.85, s * 1.25 * sk
        else:
            s_lo, s_hi = s * 1.1 * sk, s * 0.9
        if inv_logit(med) > 20:  # common rows: hedge a players-tracked wave
            s_lo = max(s_lo, s * 1.2)
        q = [med + z * (s_lo if z < 0 else s_hi) for z in Z]
        # floor mass: put q05 (and q25) exactly at 0.01 when the floor is likely
        p_floor = phi((LOGIT_LO - med) / s_lo)
        if p_floor > 0.05:
            q[0] = LOGIT_LO
        if p_floor > 0.25:
            q[1] = LOGIT_LO
        # count floor per level (wins over floor mass): C(T) >= C(now), with P(T) at the matching quantile
        if mm["post"] >= 2:
            for lv, z in enumerate(Z):
                p_lv = mm["p_t"] * math.exp(-z * mm["sig_p"])
                q[lv] = max(q[lv], logit(100 * 0.98 * mm["c_now"][i] / p_lv))
        for lv in range(1, 5):
            q[lv] = max(q[lv], q[lv - 1])
        out.append(q)
        methods.append(meth)
    ctx["diag"] = diag
    return out, methods


def apply_constraints(ctx: dict, qs: list) -> list:
    """Per quantile level: PAV down the chain, missions >= final, 100% <= final, platinum <= every row."""
    chain = [i for i in ctx["chain"] if qs[i] is not None]
    for lv in range(5):
        for i, v in zip(chain, pav_dec([qs[i][lv] for i in chain])):
            qs[i][lv] = v
        for f in ctx["final"]:
            if qs[f] is None:
                continue
            for m in ctx["missions"]:
                if qs[m] is not None:
                    qs[m][lv] = max(qs[m][lv], qs[f][lv])
            for h in ctx["hundred"]:
                if qs[h] is not None:
                    qs[h][lv] = min(qs[h][lv], qs[f][lv])
        for p in ctx["plat"]:
            if qs[p] is None:
                continue
            others = [qs[j][lv] for j in range(len(qs)) if j != p and qs[j] is not None]
            if others:
                qs[p][lv] = min(qs[p][lv], min(others))
    return qs


# ---------- run-time self-calibration (hindcast on the case's own history) ----------
LOGIT_HI = -LOGIT_LO
GRID_DAMP = [0.6, 0.8, 1.0, 1.25, 1.5]  # multiplier on D_G (effective damping capped at 1.3)
GRID_SMULT = [0.7, 0.85, 1.0, 1.2, 1.45]
GRID_SKEW = [0.8, 1.0, 1.25]
MAX_ORIGINS = 12


def pin(y: float, q: list) -> float:
    """Mean pinball loss of one row (logits), clamped as RULES Scoring does."""
    tot = 0.0
    for tau, qq in zip(LEVELS, q):
        d = y - min(LOGIT_HI, max(LOGIT_LO, qq))
        tot += 2 * max(tau * d, (tau - 1) * d)
    return tot / 5


def read_table(case: dict) -> list:
    return [(hours(r.get("at") or r["slot"]), r.get("rates") or []) for r in case["history"]]


def rate_at(rates: list, i: int):
    v = rates[i] if i < len(rates) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def persist_q(reads: list, n: int, h_at: float, h_tgt: float) -> list:
    """House persistence in logits: last read's rate (null -> 0), RW spread."""
    rw = SIGMA_RW * math.sqrt(max(h_tgt - h_at, 0) / 24)
    last = reads[-1][1]
    out = []
    for i in range(n):
        r = rate_at(last, i)
        out.append([logit(r if r is not None else 0) + z * rw for z in Z])
    return out


def house_curve_q(reads: list, n: int, h_at: float, h_tgt: float) -> list:
    """House curve in logits: per-trophy LS of logit vs ln(1+h) over the last 24 h of reads, read at the target."""
    rw = SIGMA_RW * math.sqrt(max(h_tgt - h_at, 0) / 24)
    win = [r for r in reads if r[0] >= h_at - 24]
    base = persist_q(reads, n, h_at, h_tgt)
    out = []
    for i in range(n):
        pts = [(lnx(h), logit(rate_at(rs, i))) for h, rs in win if rate_at(rs, i) is not None]
        if len(pts) < 3:
            out.append(base[i])
            continue
        b, res = ls_fit([p[0] for p in pts], [p[1] for p in pts])
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        m = my + b * (lnx(h_tgt) - mx)
        s = math.sqrt(rw ** 2 + res ** 2)
        out.append([m + z * s for z in Z])
    return out


def calibrate(case: dict, ctx: dict, states: list, reads: list, h_now: float, h_tgt: float):
    """Grid-search damping/spread/skew on hindcasts with the case's ln-time ratio, shrink 50% to the priors,
    then pick per group: ours, or a 50/50 blend with the better house method. None if history is too short."""
    n = len(case["trophies"])
    start = fit_start(states)
    if len(states) - start < 3 or h_now - states[start]["h"] < 24:
        return None
    ratio = (1 + h_tgt) / (1 + h_now)
    h_lo, h_hi = states[start]["h"] + 3, (1 + states[-1]["h"]) / ratio - 1
    if h_hi <= h_lo:
        return None
    jobs = []
    for j in range(MAX_ORIGINS):
        h0 = h_lo + (h_hi - h_lo) * j / (MAX_ORIGINS - 1)
        cut = [s for s in states if s["h"] <= h0]
        rcut = [r for r in reads if r[0] < h0]
        if not rcut or len(cut) - fit_start(cut) < 2:
            continue
        h1 = ratio * (1 + h0) - 1
        ans = [s for s in states if s["h"] <= h1][-1]
        jobs.append((h0, h1, cut, rcut, [logit(r) for r in ans["r"]]))
    if len(jobs) < 3:
        return None

    def loss_of(p, mms):
        tot, cnt = 0.0, 0
        for (h0, h1, cut, _, ys), mm in zip(jobs, mms):
            qs, _ = predict(case, ctx, cut, h0, h1, p, mm)
            qs = apply_constraints(ctx, qs)
            for i in range(n):
                if qs[i] is not None:
                    tot += pin(ys[i], qs[i])
                    cnt += 1
        return tot / max(cnt, 1)

    best, prior_loss = None, None
    for d in GRID_DAMP:
        mms = [medians(case, ctx, cut, h0, h1, dict(PRIORS, damp=d)) for h0, h1, cut, _, _ in jobs]
        for sm in GRID_SMULT:
            for sk in GRID_SKEW:
                p = dict(PRIORS, damp=d, smult=sm, skew=sk)
                lo = loss_of(p, mms)
                if d == 1.0 and sm == 1.0 and sk == 1.0:
                    prior_loss = lo
                if best is None or lo < best[0] - 1e-12:
                    best = (lo, d, sm, sk)
    params = dict(PRIORS, damp=round(0.5 * (best[1] + 1), 3), smult=round(0.5 * (best[2] + 1), 3),
                  skew=round(0.5 * (best[3] + 1), 3))
    gl = {}
    for h0, h1, cut, rcut, ys in jobs:
        qs, _ = predict(case, ctx, cut, h0, h1, params)
        qs = apply_constraints(ctx, qs)
        hc, ps = house_curve_q(rcut, n, h0, h1), persist_q(rcut, n, h0, h1)
        for i in range(n):
            if qs[i] is None:
                continue
            a = gl.setdefault(ctx["groups"][i][0], [0.0, 0.0, 0.0, 0])
            a[0] += pin(ys[i], qs[i])
            a[1] += pin(ys[i], hc[i])
            a[2] += pin(ys[i], ps[i])
            a[3] += 1
    guard, gloss = {}, {}
    for g in sorted(gl):
        o, c, p_, k = gl[g]
        guard[g] = "ours" if o <= min(c, p_) else ("curve" if c <= p_ else "persist")
        gloss[g] = [round(o / k, 4), round(c / k, 4), round(p_ / k, 4)]
    cinfo = {"origins": len(jobs), "ratio": round(ratio, 3), "loss_prior": round(prior_loss or -1, 4),
             "loss_best": round(best[0], 4), "group_loss_ours_curve_persist": gloss}
    return params, guard, cinfo


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
        params = dict(PRIORS)
        reads = read_table(case)
        guard = {}
        try:
            cal = calibrate(case, ctx, states, reads, h_now, h_tgt)
        except Exception as exc:  # visible: priors are used
            cal = None
            info["calibration_error"] = repr(exc)[:200]
        if cal:
            params, guard, info["calib"] = cal
            info["calibration_ran"] = True
            info["guard"] = guard
        qs, methods = predict(case, ctx, states, h_now, h_tgt, params)
        if any(v != "ours" for v in guard.values()):
            n = len(trophies)
            other = {"curve": house_curve_q(reads, n, h_now, h_tgt), "persist": persist_q(reads, n, h_now, h_tgt)}
            for i in range(n):
                how = guard.get(ctx["groups"][i][0], "ours")
                if qs[i] is not None and how != "ours":
                    qs[i] = [0.5 * (a + b) for a, b in zip(qs[i], other[how][i])]
                    methods[i] += "+" + how
        qs = apply_constraints(ctx, qs)
        info["params"] = params
        info["diag"] = ctx.get("diag", {})
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
