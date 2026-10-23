"""E17: replay real backbone traffic (MAWI, WIDE project) through every scheduler. Pre-registered (protocol, E17).

  python scripts/e17_realtrace.py parse <prefix.pcap.gz>   -> results/E17/mawi_windows.npz (no addresses kept)
  python scripts/e17_realtrace.py run                      -> results/E17/runs.csv, results/E17/meta.json

Parsing reads the (possibly truncated) gzip stream of a libpcap file in pure Python. Classes, fixed before any result:
latency = UDP 53, 123, 5060-5061 or 16384-32767 (either port) and ICMP/ICMPv6; video = UDP 443; bulk = everything else.
The first WINDOWS x WINDOW_PKTS IPv4/IPv6 packets form 10 windows; within a window, inter-arrival times are scaled so the
offered load on the 10 Mb/s link equals the target, and packet sizes (wire length, capped to 40-1500 B) are kept.
"""
import gzip
import hashlib
import json
import struct
import sys
import zlib
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim import SimConfig, TrafficConfig, compute, make, simulate  # noqa: E402
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import load_tuned  # noqa: E402
from drrsim.runner import code_hash  # noqa: E402
from drrsim.traffic import Trace  # noqa: E402

OUT = ROOT / "results" / "E17"
WINDOWS, WINDOW_PKTS = 10, 100_000
LOADS = (0.8, 0.95, 1.2)
SCHEDS = ["FIFO", "SP", "DRR", "RL-SP+DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR", "SCRR"]
SOURCE = "https://mawi.wide.ad.jp/mawi/samplepoint-F/2024/202401011400.pcap.gz"


def classify(proto, sport, dport):
    if proto in (1, 58):
        return 0
    if proto == 17:
        ports = (sport, dport)
        if any(p in (53, 123, 5060, 5061) or 16384 <= p <= 32767 for p in ports):
            return 0
        if 443 in ports:
            return 1
    return 2


def records(path):
    """Yield (time_s, wire_len, proto, sport, dport) from a gzip'd pcap, stopping cleanly at a truncated end.
    Reads through an offset into a growing buffer (compacted per chunk), so the cost is linear in the file size."""
    raw = open(path, "rb")
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf, pos = b"", 0

    def fill(n):
        nonlocal buf, pos
        while len(buf) - pos < n:
            chunk = raw.read(1 << 22)
            if not chunk:
                return False
            try:
                more = d.decompress(chunk)
            except zlib.error:
                return False
            buf = buf[pos:] + more
            pos = 0
        return True

    if not fill(24):
        return
    magic = struct.unpack("<I", buf[:4])[0]
    endian = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    frac = 1e-9 if magic in (0xA1B23C4D, 0x4D3CB2A1) else 1e-6
    link = struct.unpack(endian + "I", buf[20:24])[0]
    pos = 24
    rec = struct.Struct(endian + "IIII")
    while fill(16):
        sec, sub, incl, orig = rec.unpack_from(buf, pos)
        if not fill(16 + incl):
            return
        a = pos + 16
        pos = a + incl
        off = a + 14 if link == 1 else a
        if link == 1:
            et = (buf[a + 12] << 8) | buf[a + 13] if incl >= 14 else 0
            while et in (0x8100, 0x88A8) and off + 4 <= pos:
                et = (buf[off + 2] << 8) | buf[off + 3]
                off += 4
        else:
            et = 0x0800 if incl and buf[a] >> 4 == 4 else 0x86DD
        if et == 0x0800 and off + 20 <= pos:
            proto = buf[off + 9]
            l4 = off + (buf[off] & 15) * 4
        elif et == 0x86DD and off + 40 <= pos:
            proto = buf[off + 6]
            l4 = off + 40
        else:
            continue
        sport = dport = 0
        if proto in (6, 17) and l4 + 4 <= pos:
            sport = (buf[l4] << 8) | buf[l4 + 1]
            dport = (buf[l4 + 2] << 8) | buf[l4 + 3]
        yield sec + sub * frac, orig, proto, sport, dport


def parse(path):
    t, c, s = [], [], []
    need = WINDOWS * WINDOW_PKTS
    for ts, ln, proto, sp, dp in records(path):
        t.append(ts)
        c.append(classify(proto, sp, dp))
        s.append(min(1500, max(40, ln)))
        if len(t) >= need:
            break
    if len(t) < need:
        raise SystemExit(f"only {len(t)} packets in the prefix; need {need}")
    t = np.asarray(t) - t[0]
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "mawi_windows.npz", t=t, cls=np.asarray(c, np.int8), size=np.asarray(s, np.int32))
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()
    meta = {"source": SOURCE, "prefix_bytes": Path(path).stat().st_size, "prefix_sha256": h, "packets": len(t),
            "span_s": float(t[-1]), "class_share_packets": np.bincount(c, minlength=3).tolist(),
            "class_share_bytes": np.bincount(c, weights=s, minlength=3).tolist()}
    (OUT / "parse_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


def window(w, load):
    d = np.load(OUT / "mawi_windows.npz")
    sl = slice(w * WINDOW_PKTS, (w + 1) * WINDOW_PKTS)
    t, c, s = d["t"][sl], d["cls"][sl], d["size"][sl]
    t = t - t[0]
    rate_Bps = 10e6 / 8
    span = s.sum() / (load * rate_Bps)                  # duration that makes the offered load equal `load`
    t = t * (span / t[-1])
    o = np.lexsort((c, t))
    return Trace(t[o], c[o].astype(np.int8), s[o].astype(np.int32)), span


def one(args):
    w, load, name = args
    tr, span = window(w, load)
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=span, load=load))
    tuned = load_tuned()
    log = simulate(tr, make(name, **tuned.get(name, {})), cfg)
    m = compute(tr, log, cfg)
    m["W"] = max(m[f"{k.name}_p95"] / k.delay_target for k in CLASSES)
    return {"window": w, "load": load, "scheduler": name, **{k: v for k, v in m.items() if isinstance(v, (int, float))}}


def run():
    tasks = [(w, load, n) for load in LOADS for w in range(WINDOWS) for n in SCHEDS]
    with Pool() as p:
        rows = p.map(one, tasks, chunksize=2)
    import csv
    keys = list(rows[0])
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(rows)
    (OUT / "meta.json").write_text(json.dumps({"code_hash": code_hash(), "windows": WINDOWS, "window_packets": WINDOW_PKTS,
                                               "loads": LOADS, "schedulers": SCHEDS}, indent=1))
    print("wrote", OUT / "runs.csv", len(rows), "runs")


if __name__ == "__main__":
    {"parse": lambda: parse(sys.argv[2]), "run": run}[sys.argv[1]]()
