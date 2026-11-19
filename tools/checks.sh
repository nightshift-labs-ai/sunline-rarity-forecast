#!/bin/bash
# CHECKS: (a) kit double run + validator, (b) synth s00 / s01w time + info line, (c) world sim (skip with "nosim").
PY=/home/agent/tools/py313/bin/python3
R=$(cd "$(dirname "$0")/.." && pwd)
KIT=/home/agent/makefun-kit/gta6-trophy-rarity-forecast-01/x_s260/x/gta6-trophy-rarity-forecast-01-kit/input
T=/tmp/s265/chk; rm -rf $T; mkdir -p $T/o1 $T/o2 $T/s
MAKEFUN_INPUT_DIR=$KIT MAKEFUN_OUTPUT_DIR=$T/o1 $PY -P -s $R/main.py 2>$T/kit1.err
MAKEFUN_INPUT_DIR=$KIT MAKEFUN_OUTPUT_DIR=$T/o2 $PY -P -s $R/main.py 2>$T/kit2.err
cmp -s $T/o1/p00.out $T/o2/p00.out && cmp -s $T/o1/p01.out $T/o2/p01.out && echo "(a) identical" || echo "(a) DIFFER"
$PY $R/tools/check_out.py $KIT $T/o1 | tail -3
cut -c1-300 $T/kit1.err
for c in s00 s01w; do
  mkdir -p $T/s/$c/in $T/s/$c/out; cp $R/synth/$c.in $T/s/$c/in/
  s=$(date +%s.%N)
  MAKEFUN_INPUT_DIR=$T/s/$c/in MAKEFUN_OUTPUT_DIR=$T/s/$c/out $PY -P -s $R/main.py 2>$T/s/$c.err
  e=$(date +%s.%N)
  echo "(b) $c time $(echo "$e - $s" | bc)"
  $PY -c "import json; d=json.loads(open('$T/s/$c.err').read().strip().splitlines()[-1]); print('   fb_tr',d['fallback_trophies'],'fb_case',d['fallback_case'],'cal',d['calibration_ran'],'params',d.get('params'))"
  $PY $R/tools/check_out.py $T/s/$c/in $T/s/$c/out | tail -1
done
if [ "$1" != "nosim" ]; then
  $PY /home/agent/makefun/briefs/fc_s264/score.py /home/agent/makefun/briefs/fc_s264/worlds curve v3=$R/main.py 2>&1 | tail -30
fi
