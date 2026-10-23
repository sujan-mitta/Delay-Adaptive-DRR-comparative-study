"""E16 receiver: record the kernel receive timestamp (SO_TIMESTAMPNS, CLOCK_REALTIME) of every packet.

Writes CSV: seq,cls,scheduled_ns,rx_ns. Stops after `idle` seconds without packets once the first has arrived.
usage: receiver.py out.csv [idle_seconds]
"""
import select
import socket
import struct
import sys
import time

SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)    # Linux value; not exported by every Python build
out = open(sys.argv[1], "w")
idle = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
socks = {}
for c in range(3):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 << 20)
    s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
    s.bind(("10.9.0.2", 5000 + c))
    s.setblocking(False)
    socks[s.fileno()] = (s, c)
print("ready", flush=True)
poll = select.poll()
for fd in socks:
    poll.register(fd, select.POLLIN)
last, got = None, 0
while True:
    ev = poll.poll(200)
    if not ev:
        if last is not None and time.time() - last > idle:
            break
        continue
    for fd, _ in ev:
        s, c = socks[fd]
        while True:
            try:
                data, anc, _, _ = s.recvmsg(2048, socket.CMSG_SPACE(16))
            except BlockingIOError:
                break
            rx = None
            for level, kind, val in anc:
                if level == socket.SOL_SOCKET and kind == SO_TIMESTAMPNS:
                    sec, nsec = struct.unpack("qq", val[:16])
                    rx = sec * 1_000_000_000 + nsec
            seq, when = struct.unpack("!QQ", data[:16])
            out.write(f"{seq},{c},{when},{rx}\n")
            got += 1
            last = time.time()
out.close()
print(f"received {got}", flush=True)
