"""Validate .out files against their cases: python3 tools/check_out.py <input_dir> <output_dir>."""
import json
import math
import sys
from pathlib import Path


def check(case_path: Path, out_path: Path) -> list:
    errs = []
    case = json.loads(case_path.read_text(encoding="utf-8"))
    raw = out_path.read_bytes()
    if len(raw) >= 65536:
        errs.append(f"too large: {len(raw)} bytes")
    doc = json.loads(raw)
    if set(doc) != {"trophies"}:
        errs.append("top-level keys must be exactly 'trophies'")
    ids = [t["id"] for t in case["trophies"]]
    got = [r.get("id") for r in doc["trophies"]]
    if sorted(got) != sorted(ids) or len(set(got)) != len(got):
        errs.append("ids do not match the case's trophies one-to-one")
    for r in doc["trophies"]:
        q = r.get("q")
        if set(r) != {"id", "q"} or not isinstance(q, list) or len(q) != 5:
            errs.append(f"bad row shape {r}")
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100 for v in q):
            errs.append(f"id {r['id']}: value out of range {q}")
        if any(q[k] < q[k - 1] for k in range(1, 5)):
            errs.append(f"id {r['id']}: decreasing {q}")
    return errs


def main() -> None:
    inp, out = Path(sys.argv[1]), Path(sys.argv[2])
    bad = 0
    for cp in sorted(inp.glob("*.in")):
        op = out / f"{cp.stem}.out"
        errs = check(cp, op) if op.exists() else ["missing output"]
        print(f"{cp.stem}: {'OK' if not errs else 'FAIL ' + '; '.join(errs[:3])}")
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
