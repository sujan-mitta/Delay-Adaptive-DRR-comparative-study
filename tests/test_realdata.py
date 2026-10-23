"""E16/E17 tooling: the pre-registered class mapping, the pure-Python pcap reader (synthetic captures, VLAN, IPv6,
truncated gzip), window rescaling to an exact offered load, and the WSL path helper."""
import gzip
import importlib.util
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


E17 = load_script("e17_realtrace")
E16 = load_script("e16_kernel")


@pytest.mark.parametrize("proto, sport, dport, cls", [
    (17, 40000, 53, 0), (17, 123, 50000, 0), (17, 5060, 6000, 0), (17, 20000, 9999, 0), (1, 0, 0, 0), (58, 0, 0, 0),
    (17, 443, 51000, 1), (17, 51000, 443, 1), (6, 443, 51000, 2), (6, 40000, 80, 2), (17, 40000, 40001, 2), (47, 0, 0, 2),
])
def test_preregistered_class_mapping(proto, sport, dport, cls):
    assert E17.classify(proto, sport, dport) == cls


def _eth(et, payload, vlan=False):
    hdr = b"\x00" * 12 + (struct.pack("!HHH", 0x8100, 7, et) if vlan else struct.pack("!H", et))
    return hdr + payload


def _ipv4(proto, sport=0, dport=0):
    ip = bytes([0x45, 0]) + b"\x00" * 7 + bytes([proto]) + b"\x00" * 10
    return ip + (struct.pack("!HH", sport, dport) + b"\x00" * 4 if proto in (6, 17) else b"\x00" * 8)


def _ipv6(nh, sport=0, dport=0):
    return bytes([0x60]) + b"\x00" * 5 + bytes([nh, 64]) + b"\x00" * 32 + struct.pack("!HH", sport, dport) + b"\x00" * 4


def _pcap(pkts, nano=False):
    out = struct.pack("<IHHiIII", 0xA1B23C4D if nano else 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for i, (frame, wire) in enumerate(pkts):
        out += struct.pack("<IIII", 100 + i, 500 * (i + 1), len(frame), wire) + frame
    return out


def test_pcap_reader_handles_ipv4_ipv6_vlan_and_truncation(tmp_path):
    pkts = [(_eth(0x0800, _ipv4(17, 40000, 53)), 90), (_eth(0x0800, _ipv4(6, 40000, 80)), 1514),
            (_eth(0x86DD, _ipv6(17, 51000, 443)), 1250), (_eth(0x0800, _ipv4(1), vlan=True), 98),
            (_eth(0x0806, b"\x00" * 28), 60)]                       # ARP: skipped
    data = gzip.compress(_pcap(pkts))
    f = tmp_path / "x.pcap.gz"
    f.write_bytes(data[:-6])                                        # cut the gzip trailer: a truncated download
    recs = list(E17.records(f))
    assert [(r[1], r[2], r[3], r[4]) for r in recs] == [(90, 17, 40000, 53), (1514, 6, 40000, 80),
                                                       (1250, 17, 51000, 443), (98, 1, 0, 0)]
    assert recs[1][0] - recs[0][0] == pytest.approx(1 + 500e-6)
    assert [E17.classify(r[2], r[3], r[4]) for r in recs] == [0, 2, 1, 0]


def test_pcap_reader_nanosecond_timestamps(tmp_path):
    f = tmp_path / "n.pcap.gz"
    f.write_bytes(gzip.compress(_pcap([(_eth(0x0800, _ipv4(17, 1, 2)), 100)] * 2, nano=True)))
    r = list(E17.records(f))
    assert r[1][0] - r[0][0] == pytest.approx(1 + 500e-9)


def test_empty_or_garbage_file_yields_nothing(tmp_path):
    f = tmp_path / "g.pcap.gz"
    f.write_bytes(b"not a gzip file at all")
    assert list(E17.records(f)) == []


@pytest.mark.skipif(not (ROOT / "results" / "E17" / "mawi_windows.npz").exists(), reason="needs the parsed MAWI windows")
@pytest.mark.parametrize("load", E17.LOADS)
def test_window_scaling_gives_exact_offered_load(load):
    tr, span = E17.window(3, load)
    assert len(tr) == E17.WINDOW_PKTS
    assert tr.size.sum() * 8 / span / 10e6 == pytest.approx(load)
    assert tr.t[0] == 0 and tr.t[-1] == pytest.approx(span) and np.all(np.diff(tr.t) >= 0)
    assert set(np.unique(tr.cls)) <= {0, 1, 2} and tr.size.min() >= 40 and tr.size.max() <= 1500


def test_wsl_path_helper():
    assert E16.wsl_path(Path("C:/Users/x/y.csv")) == "/mnt/c/Users/x/y.csv"


@pytest.mark.parametrize("proto, sport, dport, size, strict, by_size", [
    (17, 40000, 53, 80, 0, 0), (17, 123, 123, 90, 0, 0), (1, 0, 0, 84, 0, 0),
    (17, 20000, 9999, 200, 2, 0),            # RTP-range UDP: latency in the registered mapping, not in the strict one
    (17, 51000, 443, 1200, 1, 1), (17, 51000, 443, 250, 1, 0), (6, 51000, 443, 1500, 2, 2), (6, 40000, 80, 300, 2, 0),
    (6, 40000, 80, 301, 2, 2),
])
def test_alternative_class_mappings(proto, sport, dport, size, strict, by_size):
    assert E17.classify_strict(proto, sport, dport) == strict
    assert E17.classify_size(proto, sport, dport, size) == by_size


def test_static_drr_and_ablation_tasks_are_paired_with_e1_seeds():
    from drrsim.experiments import SEEDS, STATIC_GRID, experiment_tasks
    assert len(experiment_tasks("E19TUNE", {})) == len(STATIC_GRID) ** 2 * 2 * 5
    if (ROOT / "config" / "tuned_static_drr.json").exists():
        t = experiment_tasks("E19", {})
        assert len(t) == 14 * len(SEEDS) and {x["scheduler"] for x in t} == {"DRR"}
        assert {x["seed"] for x in t} == set(SEEDS) and len({x["point"] for x in t}) == 14
