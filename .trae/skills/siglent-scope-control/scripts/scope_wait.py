"""scope_wait.py - wait for the Siglent SDS2204X HD to come back, then verify the PWM closed loop.

Typical use: power-cycle the scope, then run this. It polls the SCPI port until it accepts a
connection, then runs the requested experiments (default: idn,single,pwm) and exits non-zero if
the scope never answers.

Usage:
    python scope_wait.py                        # poll forever, 10 s interval, idn+single+pwm
    python scope_wait.py --timeout 900          # give up after 15 min
    python scope_wait.py --suite idn,pwm        # custom sequence
    python scope_wait.py --interval 5 --quiet   # only print on state change
Environment: SCOPE_IP (default 192.168.30.105), SCOPE_PORT (default 5024).
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
    ap.add_argument("--suite", default="idn,single,pwm", help="comma-separated experiments")
    ap.add_argument("--quiet", action="store_true", help="only print when the port state changes")
    args = ap.parse_args()

    host, port = lab.SCOPE, lab.PORT
    started = time.time()
    last = None
    attempt = 0
    print(f"waiting for {host}:{port} (interval {args.interval}s, timeout "
          f"{args.timeout or 'none'}s), suite={args.suite}", flush=True)

    while True:
        attempt += 1
        up = port_open(host, port)
        stamp = time.strftime("%H:%M:%S")
        if up:
            print(f"[{stamp}] attempt {attempt}: port OPEN", flush=True)
            break
        if not args.quiet or last is not False:
            print(f"[{stamp}] attempt {attempt}: port closed", flush=True)
        last = False
        if args.timeout and time.time() - started >= args.timeout:
            print("timeout reached; scope did not come back", flush=True)
            return 2
        time.sleep(args.interval)

    sc = lab.Scope()
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
