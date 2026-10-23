#!/bin/bash
# E16 testbed (run as root inside WSL2 / Linux): two namespaces joined by a veth pair; the sender's egress is a
# 10 Mb/s token bucket (tbf) whose child qdisc is the scheduler under test.
#   usage: setup.sh fifo|sp|drr        teardown: setup.sh down
set -e
MODE=$1
ip netns del e16snd 2>/dev/null || true
ip netns del e16rcv 2>/dev/null || true
[ "$MODE" = "down" ] && exit 0
ip netns add e16snd
ip netns add e16rcv
ip link add e16v0 type veth peer name e16v1
ip link set e16v0 netns e16snd
ip link set e16v1 netns e16rcv
ip -n e16snd addr add 10.9.0.1/24 dev e16v0
ip -n e16rcv addr add 10.9.0.2/24 dev e16v1
for ns in e16snd e16rcv; do ip -n $ns link set lo up; done
ip -n e16snd link set e16v0 up
ip -n e16rcv link set e16v1 up
MAC=$(ip -n e16rcv link show e16v1 | awk '/link\/ether/{print $2}')
ip -n e16snd neigh replace 10.9.0.2 lladdr "$MAC" dev e16v0 nud permanent      # no ARP during the run
TC="tc -n e16snd"
$TC qdisc add dev e16v0 root handle 1: tbf rate 10mbit burst 1600 limit 200000
case "$MODE" in
  fifo)
    $TC qdisc add dev e16v0 parent 1:1 handle 2: bfifo limit 125000 ;;
  sp)
    $TC qdisc add dev e16v0 parent 1:1 handle 2: prio bands 3 priomap 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2
    for b in 1 2 3; do $TC qdisc add dev e16v0 parent 2:$b handle 1$b: bfifo limit 41666; done ;;
  drr)
    $TC qdisc add dev e16v0 parent 1:1 handle 2: drr
    for b in 1 2 3; do
      $TC class add dev e16v0 parent 2: classid 2:$b drr quantum 1500
      $TC qdisc add dev e16v0 parent 2:$b handle 1$b: bfifo limit 41666
    done ;;
  *) echo "unknown mode $MODE"; exit 1 ;;
esac
[ "$MODE" = "fifo" ] || for b in 1 2 3; do         # class i (0..2) -> UDP port 5000+i -> band/class b = i+1
  $TC filter add dev e16v0 parent 2: protocol ip prio 1 u32 match ip dport $((4999 + b)) 0xffff flowid 2:$b
done
$TC qdisc show dev e16v0
