#!/usr/bin/env python3
# رولت گرهٔ تازهٔ SS — درجه ۲ (تست دور۲) — روی GitHub Actions
# هر اجرا: مخازن → کاندید → دور۱ (پینگ/دانلود/آپلود) → دور۲ برای قبولی‌ها → ۴ گرهٔ نهایی → gist
import os, sys, json, base64, time, urllib.parse, subprocess, urllib.request

XRAY_DIR = "/tmp/xr"
XRAY = XRAY_DIR + "/xray"
GIST = "13263cbf8ac3342eb6333825fcab2249"
FILE = "de.txt"
TOKEN = os.environ["GIST_TOKEN"]
DENY = "https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/denylist.json"  # گره‌های مُرد از ایران
COUNTRIES = [("DE", "🇩🇪 آلمان"), ("NL", "🇳🇱 هلند")]   # کشورها دونه‌دونه — اینجا اضافه شود
TARGET = 4          # ۲ کشور × ۲ گره
BASE_PORT = 11500
GOOD_CIPHERS = {"aes-128-gcm", "aes-256-gcm", "chacha20-poly1305", "chacha20-ietf-poly1305",
                "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305"}
UP1M = "/tmp/up1m.bin"

def http(url, timeout=25, headers=None):
    req = urllib.request.Request(url, headers=headers or {"user-agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()

def fetch_xray():
    os.makedirs(XRAY_DIR, exist_ok=True)
    http("https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip", 120)
    open("/tmp/xr.zip", "wb").write(http("https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip", 180))
    subprocess.run(["unzip", "-o", "-q", "/tmp/xr.zip", "xray"], cwd=XRAY_DIR, check=True)
    os.chmod(XRAY, 0o755)

# ═══ پارسر clash-yaml (بلوکی) ═══
def load_clash_ss(txt):
    out, cur = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("proxies:"):
            cur = None
            continue
        if s.startswith("- "):
            if cur and cur.get("type") == "ss" and cur.get("cipher") in GOOD_CIPHERS \
               and cur.get("server") and cur.get("port") and cur.get("password") and "plugin" not in cur:
                out.append(cur)
            cur, s = {}, s[2:].strip()
        elif cur is not None and not ln.startswith(" "):
            if cur.get("type") == "ss" and cur.get("cipher") in GOOD_CIPHERS \
               and cur.get("server") and cur.get("port") and cur.get("password") and "plugin" not in cur:
                out.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        for part in s.rstrip(",").split(","):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            k, v = k.strip().strip("'\""), v.strip().strip("'\"")
            if k and v:
                cur[k] = v
    if cur and cur.get("type") == "ss" and cur.get("cipher") in GOOD_CIPHERS \
       and cur.get("server") and cur.get("port") and cur.get("password") and "plugin" not in cur:
        out.append(cur)
    return out

# ═══ پارسر ss:// (SIP002) ═══
def load_ss_uri_lines(txt):
    out = []
    for l in txt.splitlines():
        l = l.strip()
        if not l.startswith("ss://"):
            continue
        try:
            body, _, frag = l[5:].partition("#")
            if "@¸" not in body and "@" not in body:
                continue
            userinfo, _, hostport = body.rpartition("@")
            hostport = hostport.split("/")[0].split("?")[0]
            host, _, ps = hostport.partition(":")
            if not host or not ps.isdigit():
                continue
            if ":" in userinfo:   # method:pass خام
                meth, pw = userinfo.split(":", 1)
            else:                 # base64
                pad = userinfo + "=" * (-len(userinfo) % 4)
                meth, _, pw = base64.b64decode(pad).decode().partition(":")
            if meth not in GOOD_CIPHERS:
                continue
            name = urllib.parse.unquote(frag)[:40] if frag else f"{host}:{ps}"
            out.append({"name": name, "server": host, "port": int(ps), "cipher": meth, "password": pw})
        except Exception:
            continue
    return out

# ═══ کشور هر IP (ip-api batch) ═══
def country_map(ips):
    m = {}
    for i in range(0, len(ips), 100):
        chunk = ips[i:i+100]
        req = urllib.request.Request("http://ip-api.com/batch?fields=query,countryCode",
              data=json.dumps(chunk).encode(), headers={"content-type": "application/json"})
        try:
            for r in json.load(urllib.request.urlopen(req, timeout=20)):
                m[r["query"]] = r.get("countryCode", "")
        except Exception:
            pass
        time.sleep(2)
    return m

# ═══ تست تونل ═══
def test(p, port):
    pw = p["password"]
    cfg = {"inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks"}],
           "outbounds": [{"protocol": "shadowsocks", "settings": {"servers": [
               {"address": p["server"], "port": int(p["port"]), "method": p["cipher"], "password": pw}]}}]}
    cf = f"/tmp/rt-{port}.json"
    json.dump(cfg, open(cf, "w"))
    x = subprocess.Popen([XRAY, "run", "-c", cf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = dict(p, ping=None, down=0, up=0)
    try:
        time.sleep(1.6)
        def curl(args, tm):
            return subprocess.run(["curl", "-s", "--socks5-hostname", f"127.0.0.1:{port}"] + args,
                                  capture_output=True, text=True, timeout=tm)
        t0 = time.time()
        if curl(["-o", "/dev/null", "-w", "%{http_code}", "-m", "7", "http://cp.cloudflare.com/generate_204"], 10).stdout.strip() == "204":
            r["ping"] = int((time.time() - t0) * 1000)
            rd = curl(["-o", "/dev/null", "-w", "%{speed_download}", "-m", "12",
                       "https://speed.cloudflare.com/__down?bytes=6000000"], 15)
            r["down"] = round(int(rd.stdout or 0) / 125)
            t0 = time.time()
            ru = curl(["-o", "/dev/null", "-m", "12", "-X", "POST", "--data-binary", f"@{UP1M}",
                       "http://speed.cloudflare.com/__up"], 15)
            if ru.returncode == 0:
                r["up"] = round(1000000 / max(time.time() - t0, .01) / 125)
    except Exception:
        pass
    finally:
        x.terminate()
    return r

def passes(r):
    return bool(r["ping"] and r["ping"] < 900 and r["down"] > 700 and r["up"] > 300)

def main():
    subprocess.run(["dd", "if=/dev/zero", "of=" + UP1M, "bs=1000", "count=1000"], capture_output=True)
    fetch_xray()
    cands = []
    # مخزن ۱: Au1rxx clash per-country
    for cc, fa in COUNTRIES:
        try:
            txt = http(f"https://raw.githubusercontent.com/Au1rxx/free-vpn-subscriptions/main/output/by-country/clash-{cc}.yaml").decode()
            for p in load_clash_ss(txt):
                p["cc"] = cc
                cands.append(p)
        except Exception as e:
            print(f"Au1rxx {cc}: {e}")
    # مخزن ۲: ebrasha همه‌چیز → دسته‌بندی کشور
    try:
        txt = http("https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt").decode()
        eb = load_ss_uri_lines(txt)[:400]
        cm = country_map(sorted({p["server"] for p in eb}))
        want = {cc for cc, _ in COUNTRIES}
        for p in eb:
            cc = cm.get(p["server"])
            if cc in want:
                p["cc"] = cc
                cands.append(p)
    except Exception as e:
        print("ebrasha:", e)
    # حذف تکراری
    seen, uniq = set(), []
    for p in cands:
        k = (p["server"], p["port"], p["cipher"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    print(f"کاندید یکتا: {len(uniq)}")
    # دور ۱
    r1 = []
    for i, p in enumerate(uniq):
        try:
            r = test(p, BASE_PORT + (i % 60))
        except Exception:
            continue
        r1.append(r)
        if passes(r):
            print(f"  دور۱ ✅ [{p['name'][:26]}] {p['server']}:{p['port']} {p['cipher'][:18]} پینگ={r['ping']} د={r['down']} آ={r['up']}")
    print(f"قبولی دور۱: {len(r1)}")
    # دور ۲ (درجه ۲ = تست دوبرابر)
    final = []
    for i, r in enumerate([x for x in r1 if passes(x)]):
        try:
            r2 = test(r, BASE_PORT + 100 + (i % 60))
        except Exception:
            continue
        if passes(r2):
            final.append(dict(r, ping2=r2["ping"], down2=r2["down"], up2=r2["up"], up=(r["up"] + r2["up"]) // 2))
            print(f"  دور۲ ✅ [{r['name'][:26]}] {r['server']} — پایدار")
    # انتخاب: به‌ازای هر کشور، ۲ برتر (SS-2022 اولویت؛ بعد آپلود)
    chosen, lines = [], []
    for cc, fa in COUNTRIES:
        pool = sorted([x for x in final if x["cc"] == cc],
                      key=lambda x: (not x["cipher"].startswith("2022-"), -x["up"]))[:2]
        for j, p in enumerate(pool):
            name = f"{fa} ▸ {str(j+1).zfill(2)}"
            userinfo = base64.b64encode(f"{p['cipher']}:{p['password']}".encode()).decode().rstrip("=")
            lines.append(f"ss://{userinfo}@{p['server']}:{p['port']}#{urllib.parse.quote(name)}")
            chosen.append(p)
    # اگر کشورها پر نشد → بهترین بقیه
    if len(lines) < TARGET:
        rest = sorted([x for x in final if x not in chosen], key=lambda x: -x["up"])
        for p in rest[:TARGET - len(lines)]:
            userinfo = base64.b64encode(f"{p['cipher']}:{p['password']}".encode()).decode().rstrip("=")
            lines.append(f"ss://{userinfo}@{p['server']}:{p['port']}#{urllib.parse.quote(p['name'][:30])}")
    print(f"نهایی: {len(lines)} گره")
    content = "\n".join(lines) if lines else "# هیچ گره‌ای قبول نشد"
    req = urllib.request.Request(f"https://api.github.com/gists/{GIST}",
        data=json.dumps({"files": {FILE: {"content": content}}}).encode(),
        headers={"Authorization": "token " + TOKEN, "content-type": "application/json"}, method="PATCH")
    print("gist:", json.load(urllib.request.urlopen(req, timeout=30)) and "✅")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/sum.md"), "w") as f:
        f.write(f"**کاندید:** {len(uniq)} | **دور۱:** {len(r1)} ✅ | **نهایی:** {len(lines)} گره\n\n")
        for l in lines:
            f.write(f"- `{l[:90]}…`\n")

if __name__ == "__main__":
    main()
