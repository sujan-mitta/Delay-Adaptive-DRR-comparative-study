"""E16 sender: replay a trace (CSV: t_seconds,cls,size_bytes) as UDP packets with their exact inter-arrival times.

Each frame is `size` bytes on the wire (Ethernet 14 + IP 20 + UDP 8 + payload), class i goes to port 5000+i, and the
payload starts with (seq, scheduled send time in CLOCK_REALTIME ns). Run inside the sender namespace.
usage: sender.py trace.csv start_at_realtime_ns
"""
import socket
import struct
import sys
import time

HDR = 14 + 20 + 8
trace = [line.split(",") for line in open(sys.argv[1]).read().split()]
start = int(sys.argv[2])
socks = []
for _ in range(3):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 << 20)
    s.setblocking(False)
    socks.append(s)
pad = bytes(1600)
late = fails = 0
for seq, (t, c, size) in enumerate(trace):
    when = start + int(float(t) * 1e9)
    while True:
        now = time.time_ns()
        if now >= when:
            break
        if when - now > 2_000_000:
            time.sleep((when - now - 1_000_000) / 1e9)
    if now - when > 200_000:
        late += 1
    c, size = int(c), int(size)
    payload = struct.pack("!QQ", seq, when) + pad[:size - HDR - 16]
    try:
        socks[c].sendto(payload, ("10.9.0.2", 5000 + c))
    except (BlockingIOError, OSError):
        fails += 1
print(f"sent {len(trace)} late>0.2ms {late} send_failures {fails}", flush=True)
