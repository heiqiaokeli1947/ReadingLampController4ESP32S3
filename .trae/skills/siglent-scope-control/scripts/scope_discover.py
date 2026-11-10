"""scope_discover.py - find LXI / Siglent instruments without hardcoded addresses.

No third-party dependencies: a minimal mDNS query parser plus an SSDP fallback plus an
optional TCP scan of a /24. Returns plain dicts so callers can print or pick one.

Discovery order (first hit wins for `find_scope`, all hits merged for `discover`):
  1. mDNS  _lxi._tcp.local  (the LXI standard service, 224.0.0.251:5353)
  2. SSDP  urn:schemas-upnp-org:device:Basic:1  (239.255.255.250:1900)
  3. TCP   5024 sweep of a subnet, confirmed with *IDN?  (only when --subnet is given)

Usage:
    python scope_discover.py                     # mDNS + SSDP
    python scope_discover.py --subnet 192.168.30.0/24
    python scope_discover.py --json              # machine-readable
Environment overrides: SCOPE_IP, SCOPE_PORT.
"""
import argparse
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MDNS_ADDR = ("224.0.0.251", 5353)
SSDP_ADDR = ("239.255.255.250", 1900)


# --------------------------------------------------------------------------- mDNS
def _encode_name(name):
    out = b""
    for label in name.strip(".").split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def _read_name(data, off):
    """Decode a DNS name at `off`, following compression pointers. Returns (name, next_off)."""
    labels = []
    next_off = off
    jumped = False
    while True:
        if off >= len(data):
            break
        ln = data[off]
        if ln == 0:
            off += 1
            if not jumped:
                next_off = off
            break
        if ln & 0xC0 == 0xC0:
            ptr = ((ln & 0x3F) << 8) | data[off + 1]
            if not jumped:
                next_off = off + 2
            jumped = True
            off = ptr
            continue
        labels.append(data[off + 1:off + 1 + ln].decode("ascii", "replace"))
        off += 1 + ln
    return ".".join(labels), next_off


def _parse_dns(data):
    """Return (ptr_instances, srv_by_target, a_by_name, txt_by_name) from a DNS response."""
    if len(data) < 12:
        return [], {}, {}, {}
    _, _, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    off = 12
    for _ in range(qd):
        _, off = _read_name(data, off)
        off += 4
    ptrs, srv, ips, txt = [], {}, {}, {}
    for _ in range(an):
        name, off = _read_name(data, off)
        if off + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        try:
            if rtype == 12:                      # PTR
                ptrs.append(_read_name(data, off)[0])
            elif rtype == 33 and len(rdata) >= 6:  # SRV
                _prio, _weight, port = struct.unpack(">HHH", rdata[:6])
                target = _read_name(data, off + 6)[0]
                srv[target] = {"target": target, "port": port}
            elif rtype == 1 and rdlen == 4:       # A
                ips.setdefault(name, socket.inet_ntoa(rdata))
            elif rtype == 16:                     # TXT
                pairs = {}
                for item in rdata.split(b"\x00"):
                    if b"=" in item:
                        k, v = item.split(b"=", 1)
                        pairs[k.decode("ascii", "replace")] = v.decode("ascii", "replace")
                txt[name] = pairs
        except (IndexError, struct.error):
            continue
        off += rdlen
    return ptrs, srv, ips, txt


def mdns_lxi(timeout=3.0):
    """Query _lxi._tcp.local over mDNS and return [{ip, port, name, model, source}]."""
    pkt = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + _encode_name("_lxi._tcp.local") + struct.pack(">HH", 12, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.5)
    found = {}
    try:
        s.sendto(pkt, MDNS_ADDR)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = s.recvfrom(9000)
            except socket.timeout:
                continue
            ptrs, srv, ips, txt = _parse_dns(data)
            if not ptrs and not srv:
                continue
            # only trust A records that belong to an SRV target we saw (or to a lxi instance)
            for target, info in srv.items():
                ip = ips.get(target)
                if not ip:
                    continue
                name = next((p for p in ptrs if target in p or p.split(".")[0] in target), target)
                meta = txt.get(name) or txt.get(target) or {}
                # LXI SRV points at the web/XML port (usually 80); SCPI is always 5024 here.
                found[ip] = {"ip": ip, "port": 5024, "web_port": info["port"], "name": name,
                             "model": meta.get("model") or meta.get("ty") or "",
                             "source": "mdns"}
    finally:
        s.close()
    return list(found.values())


# --------------------------------------------------------------------------- SSDP
def ssdp_lxi(timeout=2.0):
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\nMX: 1\r\nST: urn:schemas-upnp-org:device:Basic:1\r\n\r\n')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.6)
    out = {}
    try:
        s.sendto(msg.encode(), SSDP_ADDR)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            ip = addr[0]
            model = ""
            for line in data.decode("ascii", "replace").splitlines():
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
                    try:
                        xml = urllib.request.urlopen(loc, timeout=2).read().decode("utf-8", "replace")
                        for tag in ("modelName", "friendlyName"):
                            hit = xml.split(f"<{tag}>")[1].split(f"</{tag}>")[0] if f"<{tag}>" in xml else ""
                            if hit:
                                model = hit.strip()
                                break
                    except Exception:
                        pass
            out[ip] = {"ip": ip, "port": None, "name": model or "ssdp-device",
                       "model": model, "source": "ssdp"}
    finally:
        s.close()
    return list(out.values())


# --------------------------------------------------------------------------- TCP scan
def _probe_idn(ip, port=5024, timeout=0.4):
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout + 0.6)
            s.sendall(b"*IDN?\r\n")
            data = b""
            t0 = time.time()
            while time.time() - t0 < timeout + 0.4:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b">>" in data:
                    break
            txt = data.decode("ascii", "replace")
            if "Siglent" in txt or "SDS" in txt:
                return txt.strip().replace("\r", " ").replace("\n", " ")
    except OSError:
        pass
    return None


def tcp_scan(subnet, port=5024, workers=96, timeout=0.4):
    """Sweep a /24 (or any prefix) for devices that answer *IDN? with Siglent."""
    base, _, bits = subnet.partition("/")
    bits = int(bits or 24)
    if bits < 24 or bits > 30:
        raise ValueError("only /24../30 sweep is supported; pass a narrower subnet")
    prefix = base.rsplit(".", 1)[0]
    last = int(base.rsplit(".", 1)[1])
    hosts = [f"{prefix}.{i}" for i in range(1, 255)] if bits == 24 else [base]

    def work(ip):
        idn = _probe_idn(ip, port, timeout)
        return {"ip": ip, "port": port, "name": idn or "", "model": idn or "", "source": "scan"} if idn else None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return [r for r in ex.map(work, hosts) if r]


# --------------------------------------------------------------------------- public API
def discover(timeout=3.0, subnet=None, port=5024):
    """Merge mDNS, SSDP and (optional) TCP-scan results, de-duplicated by IP."""
    results = {}
    for fn in (lambda: mdns_lxi(timeout), lambda: ssdp_lxi(min(timeout, 2.0))):
        try:
            for item in fn():
                results.setdefault(item["ip"], item)
        except OSError:
            continue
    if subnet:
        for item in tcp_scan(subnet, port):
            results.setdefault(item["ip"], item)
    # enrich with *IDN? when the SCPI port is open (safe: it only reads a string)
    for item in results.values():
        if not item.get("model"):
            idn = _probe_idn(item["ip"], port)
            if idn:
                item["model"] = idn
                item["name"] = idn.split(",")[1] if "," in idn else item["name"]
    return list(results.values())


def find_scope(host=None, port=5024, subnet=None, timeout=3.0):
    """Return (ip, port). Explicit host/env wins; otherwise discover; raises if ambiguous."""
    host = host or os.environ.get("SCOPE_IP")
    if host:
        return host, int(os.environ.get("SCOPE_PORT", port))
    found = discover(timeout=timeout, subnet=subnet, port=port)
    if not found:
        raise RuntimeError(
            "no LXI instrument found. Pass --host, set SCOPE_IP, or use --subnet 192.168.30.0/24; "
            "discovery needs the host and the scope on the same L2 network with mDNS/SSDP allowed.")
    if len(found) > 1:
        listing = ", ".join(f"{f['ip']}:{f['port'] or '?'} ({f['name'] or f['source']})" for f in found)
        raise RuntimeError(f"multiple instruments found: {listing}. Pick one with --host/SCOPE_IP.")
    item = found[0]
    return item["ip"], int(item["port"] or port)


def main():
    ap = argparse.ArgumentParser(description="discover LXI/Siglent instruments")
    ap.add_argument("--subnet", help="e.g. 192.168.30.0/24 (fallback TCP sweep)")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--port", type=int, default=5024)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    found = discover(args.timeout, args.subnet, args.port)
    if args.json:
        print(json.dumps(found, indent=2))
        return 0 if found else 1
    if not found:
        print("no instrument found (try --subnet <your /24>)")
        return 1
    for f in found:
        print(f"{f['ip']:<16} port={f['port'] or '?':<6} source={f['source']:<6} {f['name'] or f['model']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
