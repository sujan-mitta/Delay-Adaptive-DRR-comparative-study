#!/bin/bash
# One E16 run (as root in WSL2/Linux): build the testbed for MODE, replay TRACE, record arrivals to OUT, tear down.
#   usage: run.sh fifo|sp|drr trace.csv out.csv
set -e
cd "$(dirname "$0")"
MODE=$1; TRACE=$2; OUT=$3
bash setup.sh "$MODE" > /dev/null
ip netns exec e16rcv python3 receiver.py "$OUT" 3 > "$OUT.rx.log" 2>&1 &
RX=$!
for i in $(seq 50); do grep -q ready "$OUT.rx.log" 2>/dev/null && break; sleep 0.1; done
START=$(( $(date +%s%N) + 1000000000 ))
ip netns exec e16snd python3 sender.py "$TRACE" "$START" > "$OUT.tx.log" 2>&1
wait $RX
tc -n e16snd -s qdisc show dev e16v0 > "$OUT.qdisc.log"
bash setup.sh down
cat "$OUT.tx.log" "$OUT.rx.log"
