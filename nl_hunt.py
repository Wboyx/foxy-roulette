#!/usr/bin/env python3
# شکارچی هلند — روزانه: همهٔ مخازن → کاندیدهای aes با خروجی NL → پایداری ۳تایی → اگر پیدا شد:
#   ۱) ورکر foxy-nl با استخر نو دیپلوی  ۲) خط NL به gist اضافه  ۳) ثبت در nl-pool.json
import os, json, time, base64, urllib.request, urllib.parse, subprocess

GH = os.environ["GIST_TOKEN"]
CF = os.environ["CF_API_TOKEN"]
AES = {"aes-128-gcm", "aes-256-gcm"}
GIST = "13263cbf8ac3342eb6333825fcab2249"
ACC = "ee9234f9f2ba43105901dffc624d696d"
D1 = "3dccbbba-1f23-4664-9803-845e985663b8"

def gh_api(url, method="GET", body=None):
    req = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "token " + GH, "content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=40))

def cf_api(url, method="GET", body=None, ct="application/json", raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, method=method, data=data,
        headers={"Authorization": "Bearer " + CF, "content-type": ct})
    return json.load(urllib.request.urlopen(req, timeout=90))

def parse_ss(text, src, out):
    try:
        pad = text.strip() + "=" * (-len(text.strip()) % 4)
        dec = base64.b64decode(pad).decode()
        if "ss://" in dec: text = dec
    except Exception: pass
    for l in text.splitlines():
        l = l.strip()
        if not l.startswith("ss://"): continue
        body, _, frag = l[5:].partition("#")
        userinfo, _, hostport = body.rpartition("@")
        hostport = hostport.split("/")[0].split("?")[0]
        host, _, ps = hostport.partition(":")
        if not host or not ps.isdigit(): continue
        try:
            if ":" in userinfo: meth, pw = userinfo.split(":", 1)
            else:
                pad = userinfo + "=" * (-len(userinfo) % 4)
                meth, _, pw = base64.b64decode(pad).decode().partition(":")
        except Exception: continue
        if meth in AES:
            out.append({"server": host, "port": int(ps), "cipher": meth, "password": pw, "src": src})

def fetch(url):
    req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=40).read().decode(errors="ignore")

XRAY = "./xray"
def setup_xray():
    os.makedirs("/tmp/xr", exist_ok=True)
    z = urllib.request.urlopen(urllib.request.Request(
        "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip",
        headers={"user-agent": "Mozilla/5.0"}), timeout=180).read()
    open("/tmp/xr/x.zip", "wb").write(z)
    subprocess.run(["unzip", "-o", "-q", "/tmp/xr/x.zip", "xray"], cwd="/tmp/xr", check=True)
    os.chmod("/tmp/xr/xray", 0o755)
    return "/tmp/xr/xray"

def test(xray, n, port, speed=False):
    cfg = {"inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks"}],
           "outbounds": [{"protocol": "shadowsocks", "settings": {"servers": [
               {"address": n["server"], "port": int(n["port"]), "method": n["cipher"], "password": n["password"]}]}}]}
    json.dump(cfg, open(f"/tmp/hn-{port}.json", "w"))
    x = subprocess.Popen([xray, "run", "-c", f"/tmp/hn-{port}.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = dict(n, ping=None, down=0, up=0, exit="")
    try:
        time.sleep(1.7)
        t0 = time.time()
        rp = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "7",
            "--socks5-hostname", f"127.0.0.1:{port}", "https://www.gstatic.com/generate_204"],
            capture_output=True, text=True)
        if rp.stdout.strip() == "204":
            r["ping"] = int((time.time() - t0) * 1000)
            g = subprocess.run(["curl", "-s", "-m", "7", "--socks5-hostname", f"127.0.0.1:{port}",
                "http://ip-api.com/json/?fields=countryCode,city"], capture_output=True, text=True)
            try:
                gg = json.loads(g.stdout); r["exit"] = gg.get("countryCode", "") + ":" + gg.get("city", "")
            except Exception: pass
            if speed and r["exit"].startswith("NL"):
                rd = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{speed_download}", "-m", "12",
                    "--socks5-hostname", f"127.0.0.1:{port}", "https://proof.ovh.net/files/10Mb.dat"],
                    capture_output=True, text=True)
                r["down"] = round(int(rd.stdout or 0) / 125)
    except Exception: pass
    finally: x.terminate()
    return r

def main():
    xray = setup_xray()
    cands = []
    for url, src in [
        ("https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt", "ebra"),
        ("https://github.com/Epodonios/v2ray-configs/raw/main/Splitted-By-Protocol/ss.txt", "epo"),
        ("https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/ss.txt", "barry"),
    ]:
        try: parse_ss(fetch(url), src, cands)
        except Exception as e: print(src, "خطا:", str(e)[:60])
    state = json.load(open("nl-state.json"))
    deny = set()
    try:
        deny = set(json.load(urllib.request.urlopen(
            "https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/denylist.json", timeout=20))["ips"])
    except Exception: pass
    seen, uniq = set(), []
    for c in cands:
        k = (c["server"], c["port"], c["cipher"])
        if k in seen or c["server"] in deny: continue
        seen.add(k); uniq.append(c)
    ips = sorted({c["server"] for c in uniq})
    cm = {}
    for i in range(0, len(ips), 100):
        ch = ips[i:i+100]
        req = urllib.request.Request("http://ip-api.com/batch?fields=query,countryCode",
              data=json.dumps(ch).encode(), headers={"content-type": "application/json"})
        try:
            for r in json.load(urllib.request.urlopen(req, timeout=20)):
                cm[r["query"]] = r.get("countryCode", "")
        except Exception: pass
        time.sleep(2)
    nl = [c for c in uniq if cm.get(c["server"]) == "NL"]
    print("هلند کاندید:", len(nl))
    hits = []
    for i, n in enumerate(nl):
        try: r = test(xray, n, 13600 + (i % 40), speed=True)
        except Exception: continue
        if r["exit"].startswith("NL") and r["down"] > 700:
            hits.append(r); print("کاندید:", n["server"], r["exit"], r["down"])
    stable = []
    for r in hits:
        ok = 0
        for t in range(3):
            rr = test(xray, r, 13800 + t)
            if rr["exit"].startswith("NL"): ok += 1
        if ok >= 2:
            stable.append(r); print("پایدار:", r["server"], f"{ok}/3")
    stable.sort(key=lambda x: (-x["down"], x["ping"] or 9999))
    pool = [{"n": f"nl-{i}", "h": s["server"], "p": str(s["port"]), "k": s["password"],
             "kl": "16" if s["cipher"] == "aes-128-gcm" else "32"} for i, s in enumerate(stable[:3])]
    json.dump({"found": len(stable), "pool": pool, "checked_at": time.strftime("%Y-%m-%d %H:%M")},
              open("nl-pool.json", "w"), ensure_ascii=False, indent=1)
    if not pool:
        print("امروز هلند پایدار پیدا نشد")
        return
    # ۱) دیپلوی ورکر NL با استخر نو:
    boundary = "----foxyNL"
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": state["uuid"]},
              {"type": "plain_text", "name": "WNAME", "text": "nl-acc1"},
              {"type": "plain_text", "name": "SRV_ID", "text": "nl"},
              {"type": "plain_text", "name": "SS_POOL", "text": json.dumps(pool)},
              {"type": "d1", "name": "DB", "id": D1}]}
    code = open("de-worker.js", "rb").read()
    body = (f"--{boundary}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"m.json\"\r\n"
            f"content-type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"w.js\"\r\n"
            f"content-type: application/javascript+module\r\n\r\n").encode() + code + \
           f"\r\n--{boundary}--\r\n".encode()
    up = cf_api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/foxy-nl",
                "PUT", ct=f"multipart/form-data; boundary={boundary}", raw=body)
    print("دیپلوی foxy-nl:", up.get("success"))
    cf_api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/foxy-nl/subdomain",
           "POST", {"enabled": True})
    # ۲) خط NL به gist:
    gist = gh_api(f"https://api.github.com/gists/{GIST}")
    de_content = gist["files"]["de.txt"]["content"]
    nl_lines = [l for l in de_content.splitlines() if "foxy-nl" in l or "%F0%9F%87%B3%F0%9F%87%B1" in l]
    if not nl_lines:
        host = "foxy-nl.mahdi-wz10.workers.dev"
        q = urllib.parse.urlencode({"encryption": "none", "security": "tls", "sni": host, "fp": "chrome",
                                    "type": "ws", "host": host, "path": "/" + state["uuid"], "alpn": "http/1.1"})
        nl_lines = [f"vless://{state['uuid']}@{host}:443?{q}#{urllib.parse.quote('🇳🇱 Netherlands 🦊')}"]
    new_content = de_content.rstrip() + "\n" + "\n".join(nl_lines) if "foxy-nl" not in de_content else de_content
    gh_api(f"https://api.github.com/gists/{GIST}", "PATCH", {"files": {"de.txt": {"content": new_content}}})
    print("gist به‌روز شد ✅ — هلند به ساب اضافه شد")

    try:
        hunt_de_backup()
    except Exception as e:
        print("hunt_de_backup خطا:", str(e)[:120])


# ═══ نجات‌دهندهٔ آلمان: اگر عضو فعال افت کرده بود، جایگزین پایدار پیدا و فعال کن ═══
def hunt_de_backup():
    import json as _json, subprocess, time as _time, urllib.request
    nodes = gh_api("https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/de-nodes.json")
    if isinstance(nodes, str): nodes = _json.loads(nodes)
    de_node = [n for n in nodes["nodes"] if n["id"] == "de"][0]
    cur_pool = _json.loads(gh_api("https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/de-pool.json"))
    if isinstance(cur_pool, str): cur_pool = _json.loads(cur_pool)
    # سلامت عضو فعلی (۲ تست سریع):
    xray = setup_xray()
    active_ok = 0
    for t in range(2):
        r = test(xray, {"server": cur_pool[0]["h"], "port": int(cur_pool[0]["p"]),
                        "cipher": "aes-128-gcm" if cur_pool[0]["kl"] == "16" else "aes-256-gcm",
                        "password": cur_pool[0]["k"]}, 15990, speed=False)
        if r and r.get("exit", "").startswith("DE"): active_ok += 1
    print(f"عضو فعلی آلمان: {active_ok}/2")
    if active_ok >= 2:
        print("آلمان سالم — شکار جایگزین لازم نیست")
        return
    # شکار جایگزین DE (همان منابع):
    cands = []
    for url, src in [
        ("https://cdn.jsdelivr.net/gh/xiaoji235/airport-free/v2ray.txt", "airport"),
        ("https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/master/sub/proxies.txt", "mahdi0024"),
        ("https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2", "v2rayfree"),
        ("https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/refs/heads/main/configs/proxy_configs.txt", "anonymou3")]:
        try: parse_ss(fetch(url), src, cands)
        except Exception as e: print("منبع:", str(e)[:40])
    ips = sorted({c["server"] for c in cands})
    cm = {}
    for i in range(0, len(ips), 100):
        ch = ips[i:i+100]
        req = urllib.request.Request("http://ip-api.com/batch?fields=query,countryCode",
              data=_json.dumps(ch).encode(), headers={"content-type": "application/json"})
        try:
            for r in _json.load(urllib.request.urlopen(req, timeout=20)): cm[r["query"]] = r.get("countryCode", "")
        except Exception: pass
        _time.sleep(2)
    de = [c for c in cands if cm.get(c["server"]) == "DE"
          and not (c["server"] == cur_pool[0]["h"] and str(c["port"]) == str(cur_pool[0]["p"]))]
    print("کاندید جایگزین آلمان:", len(de))
    best = None
    for i, n in enumerate(de):
        ok = 0
        for t in range(2):
            r = test(xray, n, 15960 + t, speed=True)
            if r and r.get("exit", "").startswith("DE") and r.get("down", 0) > 700: ok += 1
        if ok >= 2:
            best = n; break
    if not best:
        print("جایگزین آلمانی پیدا نشد — عضو فعلی می‌ماند")
        return
    # فعال‌سازی: استخر نو (برنده اول) + دیپلوی foxy-de3 + سطر active_srv:
    new_pool = [{"n": f"de-{best['city'].lower()}-{best['server']}" if best.get("city") else f"de-{best['server']}",
                 "h": best["server"], "p": str(best["port"]), "k": best["password"],
                 "kl": "16" if best["cipher"] == "aes-128-gcm" else "32"}] + cur_pool
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": de_node["uuid"]},
              {"type": "plain_text", "name": "WNAME", "text": "de-acc1"},
              {"type": "plain_text", "name": "SRV_ID", "text": "de"},
              {"type": "plain_text", "name": "SS_POOL", "text": _json.dumps(new_pool)},
              {"type": "d1", "name": "DB", "id": de_node["d1"]}]}
    code = urllib.request.urlopen("https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/de-worker.js", timeout=60).read()
    import uuid as _u
    b = str(_u.uuid4()); body = (
        f"--{b}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"m.json\"\r\n"
        f"content-type: application/json\r\n\r\n{_json.dumps(meta)}\r\n"
        f"--{b}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"w.js\"\r\n"
        f"content-type: application/javascript+module\r\n\r\n").encode() + code + f"\r\n--{b}--\r\n".encode()
    up = cf_api(f"https://api.cloudflare.com/client/v4/accounts/{de_node['account']}/workers/scripts/foxy-de3",
                "PUT", ct=f"multipart/form-data; boundary={b}", raw=body)
    print("دیپلوی foxy-de3 با عضو نو:", up.get("success"))
    cf_api("https://api.cloudflare.com/client/v4/accounts/" + de_node["account"] +
           "/d1/database/" + de_node["d1"] + "/query",
           body={"sql": "INSERT INTO active_srv (id, name, updated) VALUES ('de', ?1, datetime('now')) "
                        "ON CONFLICT(id) DO UPDATE SET name = ?1, updated = datetime('now')",
                 "params": [new_pool[0]["n"]]})
    gh_api("https://api.github.com/repos/Wboyx/foxy-roulette/contents/de-pool.json", "PUT",
           {"message": "de backup activated", "content": __import__("base64").b64encode(
               _json.dumps(new_pool, indent=1).encode()).decode()})
    print("✅ عضو نو فعال شد:", new_pool[0]["n"])

if __name__ == "__main__":
    main()
