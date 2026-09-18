#!/usr/bin/env python3
# پل SOCKS5 → VLESS+WS (تست نود اختصاصی — فرمت کلاسیک مثل V2Box)
import socket, struct, threading, uuid, sys, select

UUID = sys.argv[1] if len(sys.argv) > 1 else "7f3b9c2e-4a81-4d6f-9b25-8c1e5a7f0d34"
import sys as _s
WS_HOST = _s.argv[3] if len(_s.argv) > 3 else "foxy-node.mahdi-wz10.workers.dev"
WS_PORT = 443
LISTEN = int(sys.argv[2]) if len(sys.argv) > 2 else 11700

import ssl, base64, os

def ws_connect(path):
    raw = socket.create_connection((WS_HOST, WS_PORT), timeout=15)
    ctx = ssl.create_default_context()
    s = ctx.wrap_socket(raw, server_hostname=WS_HOST)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {WS_HOST}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("WS handshake failed — no data")
        buf += chunk
    status = buf.split(b"\r\n")[0].decode()
    if "101" not in status:
        raise RuntimeError("WS handshake rejected: " + status)
    return s, buf.split(b"\r\n\r\n", 1)[1]

def ws_send(s, data):
    out = b""
    i = 0
    while i < len(data):
        chunk = data[i:i + 65535]
        i += len(chunk)
        mask = os.urandom(4)
        hdr = b"\x82"  # FIN+binary
        ln = len(chunk)
        if ln < 126:
            hdr += bytes([0x80 | ln])
        elif ln < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", ln)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", ln)
        masked = bytes(b ^ mask[j % 4] for j, b in enumerate(chunk))
        out += hdr + mask + masked
    s.sendall(out)

def ws_recv(s):
    """یک پیام کامل WS برمی‌گرداند"""
    hdr = b""
    while len(hdr) < 2:
        c = s.recv(2 - len(hdr))
        if not c:
            return None
        hdr += c
    ln = hdr[1] & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", s.recv(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", s.recv(8))[0]
    data = s.recv(ln) if ln else b""
    while len(data) < ln:
        c = s.recv(ln - len(data))
        if not c:
            return None
        data += c
    return data

def tunnel(client):
    try:
        # هدر SOCKS5
        client.recv(256)
        client.sendall(b"\x05\x00")
        req = client.recv(256)
        atyp = req[3]
        if atyp == 1:
            host = socket.inet_ntoa(req[4:8]); port = struct.unpack(">H", req[8:10])[0]; rest = req[10:]
        elif atyp == 3:
            ln = req[4]; host = req[5:5+ln].decode(); port = struct.unpack(">H", req[5+ln:7+ln])[0]; rest = req[7+ln:]
        else:
            client.close(); return
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00" + struct.pack(">H", port))
        try:
            ws, leftover = ws_connect(f"/{UUID}")
            print(f"[bridge] ws ok host={host}:{port}", flush=True)
        except Exception as e:
            print(f"[bridge] ws_fail: {e}", flush=True)
            client.close(); return
        uid = uuid.UUID(UUID).bytes
        vreq = b"\x00" + uid + b"\x00" + b"\x01" + struct.pack(">H", port) + b"\x02" + bytes([len(host)]) + host.encode() + rest
        ws_send(ws, vreq)
        hdr = ws_recv(ws)
        print(f"[bridge] hdr={(hdr[:4].hex() if hdr else None)}", flush=True)
        if not hdr or hdr[:2] != b"\x00\x00":
            client.close(); return
        if hdr[2:]:
            client.sendall(hdr[2:])
        stop = threading.Event()
        def up():
            try:
                while not stop.is_set():
                    d = client.recv(65536)
                    if not d:
                        break
                    ws_send(ws, d)
            except Exception:
                pass
            stop.set()
            try: client.close()
            except Exception: pass
        def down():
            try:
                while not stop.is_set():
                    m = ws_recv(ws)
                    if m is None:
                        break
                    if m:
                        client.sendall(m)
            except Exception:
                pass
            stop.set()
            try: client.close()
            except Exception: pass
        threading.Thread(target=up, daemon=True).start()
        down()
    except Exception:
        try: client.close()
        except Exception: pass

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LISTEN))
srv.listen(32)
print(f"پل روی 127.0.0.1:{LISTEN} → {WS_HOST} (VLESS+WS)")
while True:
    c, _ = srv.accept()
    threading.Thread(target=tunnel, args=(c,), daemon=True).start()
