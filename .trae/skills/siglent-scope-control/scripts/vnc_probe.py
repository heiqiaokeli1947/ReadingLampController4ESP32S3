# vnc_probe.py — minimal RFB handshake probe for the SDS2204X HD
import os, socket, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scope_discover import find_scope

HOST = os.environ.get("SCOPE_IP")
PORT = 5900
if not HOST:
    HOST, _ = find_scope(subnet=os.environ.get("SCOPE_SUBNET"))

def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError(f"closed after {len(buf)}/{n} bytes")
        buf += c
    return buf

s = socket.create_connection((HOST, PORT), timeout=6)
s.settimeout(6)

banner = recv_exact(s, 12)
print("server banner:", banner)
s.sendall(b"RFB 003.008\n")

n = recv_exact(s, 1)[0]
types = list(recv_exact(s, n))
print("security types:", types, "(1=None, 2=VNC auth)")

if 1 in types:
    s.sendall(struct.pack("B", 1))          # choose None
    res = struct.unpack(">I", recv_exact(s, 4))[0]
    print("security result:", res)
elif 2 in types:
    print("VNC auth required — password needed (web password may apply)")
    s.close(); sys.exit(0)
else:
    s.close(); sys.exit(0)

s.sendall(struct.pack("B", 1))              # ClientInit: shared=1
w, h = struct.unpack(">HH", recv_exact(s, 4))
pf = recv_exact(s, 16)
name_len = struct.unpack(">I", recv_exact(s, 4))[0]
name = recv_exact(s, name_len)
bpp, depth, bigendian, truecolor = pf[0], pf[1], pf[2], pf[3]
rmax, gmax, bmax = struct.unpack(">HHH", pf[4:10])
rsh, gsh, bsh = pf[10], pf[11], pf[12]
print(f"framebuffer: {w}x{h}, bpp={bpp}, depth={depth}, bigendian={bigendian}, truecolor={truecolor}")
print(f"max rgb=({rmax},{gmax},{bmax}) shifts=({rsh},{gsh},{bsh})")
print("desktop name:", name)
s.close()
print("HANDSHAKE OK — VNC server alive")
