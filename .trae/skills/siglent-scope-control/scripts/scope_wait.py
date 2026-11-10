"""scope_wait.py - wait for the Siglent SDS2204X HD to come back, then verify the PWM closed loop.

Typical use: power-cycle the scope, then run this. It discovers the scope over LXI (mDNS/SSDP) on
every attempt — no IP is baked in — and polls the SCPI port until it accepts a connection. It then
runs the requested experiments (default: idn,pwm — no screenshots) and exits non-zero if the scope
never answers.

Screenshots are unsafe unattended (they raise a modal dialog that wedges the instrument app), so
the default suite deliberately avoids `single`. Add it only with SCOPE_ALLOW_SCREENSHOT=1 and a
person standing at the scope.

Usage:
    python scope_wait.py                          # discover, poll forever, 10 s interval, idn+pwm
    python scope_wait.py --host 192.168.30.105    # skip discovery
    python scope_wait.py --subnet 192.168.30.0/24 # discovery fallback via TCP sweep
    python scope_wait.py --timeout 900            # give up after 15 min
    python scope_wait.py --dut 192.168.30.74 --dut-pwd *** --channels '{"1":...}'
Environment: SCOPE_IP, SCOPE_PORT, SCOPE_SUBNET, DUT_IP, DUT_PWD, SCOPE_CHANNELS.
"""
import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scope_lab as lab


def port_open(host, port, timeout=3.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between probes")
    ap.add_argument("--timeout", type=float, default=0, help="stop after N seconds (0 = forever)")
    ap.add_argument("--suite", default="idn,pwm", help="comma-separated experiments")
    ap.add_argument("--quiet", action="store_true", help="only print when the port state changes")
    ap.add_argument("--host", help="scope IP; default: discover over LXI")
    ap.add_argument("--port", type=int, help="SCPI port (default 5024)")
    ap.add_argument("--subnet", help="e.g. 192.168.30.0/24, enables TCP-scan fallback")
    ap.add_argument("--dut", help="DUT IP for the /status cross-check")
    ap.add_argument("--dut-pwd", help="DUT API password")
    ap.add_argument("--channels", help='probe map JSON, e.g. {"1":{"name":"white","key":"whiteApplied"}}')
    args = ap.parse_args()

    if args.host:
        lab.HOST = args.host
    if args.port:
        lab.PORT = args.port
    if args.subnet:
        os.environ["SCOPE_SUBNET"] = args.subnet
    if args.dut:
        os.environ["DUT_IP"] = args.dut
    if args.dut_pwd:
        os.environ["DUT_PWD"] = args.dut_pwd
    if args.channels:
        os.environ["SCOPE_CHANNELS"] = args.channels

    started = time.time()
    last = None
    attempt = 0
    print(f"waiting for scope ({lab.HOST or 'LXI discovery'}):{lab.PORT} "
          f"(interval {args.interval}s, timeout {args.timeout or 'none'}s), suite={args.suite}",
          flush=True)

    host = port = None
    while True:
        attempt += 1
        try:
            host, port = lab.find_scope(lab.HOST, lab.PORT, subnet=os.environ.get("SCOPE_SUBNET"))
        except RuntimeError as e:
            host, port = None, None
            note = str(e).split(".")[0]
        else:
            note = ""
        up = bool(host) and port_open(host, port)
        stamp = time.strftime("%H:%M:%S")
        if up:
            print(f"[{stamp}] attempt {attempt}: {host}:{port} OPEN", flush=True)
            break
        if not args.quiet or last is not False:
            where = f"{host}:{port}" if host else "-"
            print(f"[{stamp}] attempt {attempt}: {where} closed"
                  + (f" ({note})" if note else ""), flush=True)
        last = False
        if args.timeout and time.time() - started >= args.timeout:
            print("timeout reached; scope did not come back", flush=True)
            return 2
        time.sleep(args.interval)

    sc = lab.Scope(host, port)
    try:
        for name in [x.strip() for x in args.suite.split(",") if x.strip()]:
            print(f"===== {name} =====", flush=True)
            if name == "idn":
                lab.exp_idn(sc)
            elif name == "single":
                lab.exp_single(sc)
            elif name == "pwm":
                lab.exp_pwm(sc)
            elif name == "params":
                lab.exp_params(sc)
            elif name == "runall":
                lab.exp_runall(sc)
            else:
                print(f"skip unknown experiment {name}", flush=True)
    finally:
        sc.close()
    print("done; screenshots in", lab.OUT, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
