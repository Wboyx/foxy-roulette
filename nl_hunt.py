#!/usr/bin/env python3
# 🦊 شکارچی چندکشوری (هر ۶ ساعت): NL/FR/GB — هر کشور با ≥۲ عضو پایدار خودکار دیپلوی و به ساب می‌آید.
# + ارتقای استخر کشور فعال + نجات‌دهندهٔ آلمان. uuidها هرگز در ریپو نیستند — فقط در gist.
import os, json, time, random, base64, subprocess, urllib.request, urllib.parse, uuid as uuidlib

GH = os.environ["GIST_TOKEN"]
CF = os.environ["CF_API_TOKEN"]
ACC = "ee9234f9f2ba43105901dffc624d696d"
D1 = "3dccbbba-1f23-4664-9803-845e985663b8"
GIST = "13263cbf8ac3342eb6333825fcab2249"
CODE_URL = "https://raw.githubusercontent.com/Wboyx/foxy-roulette/main/de-worker.js"
REPO = "https://raw.githubusercontent.com/Wboyx/foxy-roulette/main"
AES = {"aes-128-gcm", "aes-256-gcm"}
COUNTRIES = {
    "NL": {"worker": "foxy-nl", "host": "foxy-nl.mahdi-wz10.workers.dev", "label": "\U0001F1F3\U0001F1F1 Netherlands \U0001F98A", "staging": "nl.txt"},
    "FR": {"worker": "foxy-fr", "host": "foxy-fr.mahdi-wz10.workers.dev", "label": "\U0001F1EB\U0001F1F7 France \U0001F98A", "staging": None},
    "GB": {"worker": "foxy-gb", "host": "foxy-gb.mahdi-wz10.workers.dev", "label": "\U0001F1EC\U0001F1E7 United Kingdom \U0001F98A", "staging": None},
}

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

def fetch(url):
    return urllib.request.urlopen(url, timeout=60).read().decode()

def parse_ss(text, src, out):
    raw = text
    try:
        pad = raw.strip() + "=" * (-len(raw.strip()) % 4)
        dec = base64.b64decode(pad).decode()
        if "ss://" in dec: raw = dec
    except Exception: pass
    for l in raw.splitlines():
        l = l.strip()
        if not l.startswith("ss://"): continue
        if "plugin=" in l: continue  # پلاگین‌دارها با SS ساده کار نمی‌کنند
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

def setup_xray():
    if not os.path.exists("xray"):
        arch = "Xray-linux-64.zip"
        urllib.request.urlretrieve(f"https://github.com/XTLS/Xray-core/releases/latest/download/{arch}", "/tmp/x.zip")
        subprocess.run(["unzip", "-o", "/tmp/x.zip", "xray"], check=True)
    subprocess.run(["chmod", "+x", "xray"])
    return os.path.abspath("xray")

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
            geo = subprocess.run(["curl", "-s", "-m", "7", "--socks5-hostname", f"127.0.0.1:{port}",
                                  "http://ip-api.com/json/?fields=countryCode,city"], capture_output=True, text=True)
            try:
                g = json.loads(geo.stdout); r["exit"] = g.get("countryCode", "") + ":" + g.get("city", "")
            except Exception: pass
            r["ping"] = int((time.time() - t0) * 1000)
            if speed:
                rd = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{speed_download}", "-m", "12",
                                     "--socks5-hostname", f"127.0.0.1:{port}", "https://proof.ovh.net/files/10Mb.dat"],
                                    capture_output=True, text=True)
                r["down"] = round(int(rd.stdout or 0) / 125)
    except Exception: pass
    finally: x.terminate()
    return r

def geo_batch(ips):
    cm = {}
    for i in range(0, len(ips), 100):
        ch = ips[i:i + 100]
        req = urllib.request.Request("http://ip-api.com/batch?fields=query,countryCode,city",
              data=json.dumps(ch).encode(), headers={"content-type": "application/json"})
        try:
            for r in json.load(urllib.request.urlopen(req, timeout=20)):
                cm[r["query"]] = (r.get("countryCode", ""), r.get("city", ""))
        except Exception: pass
        time.sleep(2)
    return cm

def harvest(targets):
    cands = []
    for url, src in [
        ("https://cdn.jsdelivr.net/gh/xiaoji235/airport-free/v2ray.txt", "airport"),
        ("https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2", "v2rayfree"),
        ("https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/master/sub/proxies.txt", "mahdi0024"),
        ("https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/refs/heads/main/configs/proxy_configs.txt", "anonymou3"),
        ("https://raw.githubusercontent.com/HosseinKoofi/GO_V2rayCollector/main/ss_iran.txt", "koofi"),
        ("https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/ss.txt", "epodonios"),
        ("https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt", "eternity")]:
        try: parse_ss(fetch(url), src, cands)
        except Exception as e: print("منبع خطا:", src, str(e)[:50])
    try: deny = set(json.loads(fetch(REPO + "/denylist.json"))["ips"])
    except Exception: deny = set()
    seen, uniq = set(), []
    for c in cands:
        k = (c["server"], c["port"], c["cipher"])
        if k in seen or c["server"] in deny: continue
        seen.add(k); uniq.append(c)
    print("کل aes یکتا:", len(uniq))
    cm = geo_batch(sorted({c["server"] for c in uniq}))
    out = {}
    for cc in targets:
        out[cc] = [c for c in uniq if cm.get(c["server"], ("", ""))[0] == cc]
        print(cc, "→", len(out[cc]), "کاندید")
    return out

def gist_files():
    g = gh_api(f"https://api.github.com/gists/{GIST}")
    return {f: g["files"][f]["content"] for f in g["files"]}

def line_of(content, host):
    for l in content.splitlines():
        if l.startswith("vless://") and f"@{host}:" in l:
            return l
    return None

def make_line(uuid, host, label):
    q = urllib.parse.urlencode({"encryption": "none", "security": "tls", "sni": host, "fp": "chrome",
                                "type": "ws", "host": host, "path": "/" + uuid, "alpn": "http/1.1"})
    return f"vless://{uuid}@{host}:443?{q}#{urllib.parse.quote(label)}"

def uuid_from_line(line):
    return line[8:].split("@")[0]

def get_nodes():
    return json.loads(fetch(REPO + "/de-nodes.json"))

def put_repo(path, content, msg):
    try:
        g = gh_api(f"https://api.github.com/repos/Wboyx/foxy-roulette/contents/{path}")
        sha = g.get("sha")
    except Exception: sha = None
    body = {"message": msg, "content": base64.b64encode(content.encode() if isinstance(content, str) else content).decode()}
    if sha: body["sha"] = sha
    gh_api(f"https://api.github.com/repos/Wboyx/foxy-roulette/contents/{path}", "PUT", body)

def build_pool(cc, stable, cap=4):
    pool = []
    for i, s in enumerate(stable[:cap]):
        city = (s.get("city") or s["exit"].split(":")[-1] if s.get("exit") else s["server"])
        pool.append({"n": f"{cc.lower()}-{str(city).lower()}-{i}", "h": s["server"], "p": str(s["port"]),
                     "k": s["password"], "kl": "16" if s["cipher"] == "aes-128-gcm" else "32"})
    return pool

def deploy_worker(worker, uuid, srvid, pool, wname):
    code = urllib.request.urlopen(CODE_URL, timeout=60).read()
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": uuid},
              {"type": "plain_text", "name": "WNAME", "text": wname},
              {"type": "plain_text", "name": "SRV_ID", "text": srvid},
              {"type": "plain_text", "name": "SS_POOL", "text": json.dumps(pool)},
              {"type": "d1", "name": "DB", "id": D1}]}
    b = str(uuidlib.uuid4())
    body = (f"--{b}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"m.json\"\r\n"
            f"content-type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{b}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"worker.js\"\r\n"
            f"content-type: application/javascript+module\r\n\r\n").encode() + code + f"\r\n--{b}--\r\n".encode()
    up = cf_api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/{worker}",
                "PUT", ct=f"multipart/form-data; boundary={b}", raw=body)
    print("دیپلوی", worker, ":", up.get("success"))
    cf_api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/{worker}/subdomain",
           "POST", {"enabled": True})
    return up.get("success")

def enable_country(cc, stable):
    cfg = COUNTRIES[cc]
    files = gist_files()
    de = files["de.txt"]
    line = line_of(de, cfg["host"])
    if not line and cfg["staging"] and cfg["staging"] in files:
        line = line_of(files[cfg["staging"]], cfg["host"])
    uuid = uuid_from_line(line) if line else str(uuidlib.uuid4())
    pool = build_pool(cc, stable)
    ok = deploy_worker(cfg["worker"], uuid, cc.lower(), pool, cc.lower() + "-acc1")
    if not ok: return False
    if not line_of(de, cfg["host"]):
        new_content = de.rstrip() + "\n" + make_line(uuid, cfg["host"], cfg["label"])
        gh_api(f"https://api.github.com/gists/{GIST}", "PATCH", {"files": {"de.txt": {"content": new_content}}})
        print(f"خط {cc} به ساب اضافه شد ✅")
    if cfg["staging"]:
        gh_api(f"https://api.github.com/gists/{GIST}", "PATCH",
               {"files": {cfg["staging"]: {"content": make_line(uuid, cfg["host"], cfg["label"])}}})
    put_repo(f"{cc.lower()}-pool.json", json.dumps(pool, indent=1), f"{cc} pool auto")
    nodes = get_nodes()
    entry = {"id": cc.lower(), "prefix": cfg["worker"], "worker": cfg["worker"], "host": cfg["host"],
             "label": cfg["label"], "srv_id": cc.lower(), "pool_file": f"{cc.lower()}-pool.json",
             "gist_file": "de.txt", "gist": GIST, "d1": D1, "account": ACC}
    nodes["nodes"] = [n for n in nodes["nodes"] if n["id"] != cc.lower()] + [entry]
    put_repo("de-nodes.json", json.dumps(nodes, indent=1), f"node {cc} added (no secrets)")
    print(f"✅ {cc} فعال شد — استخر {len(pool)} عضوی")
    return True

def refresh_pool(cc, stable):
    cfg = COUNTRIES[cc]
    try: cur = json.loads(fetch(REPO + f"/{cc.lower()}-pool.json"))
    except Exception: cur = []
    if len(stable) <= len(cur): return False
    pool = build_pool(cc, stable)
    line = line_of(gist_files()["de.txt"], cfg["host"])
    if not line: return False
    uuid = uuid_from_line(line)
    deploy_worker(cfg["worker"], uuid, cc.lower(), pool, cc.lower() + "-acc1")
    put_repo(f"{cc.lower()}-pool.json", json.dumps(pool, indent=1), f"{cc} pool refresh")
    print(f"↑ استخر {cc} به {len(pool)} عضو ارتقا یافت")
    return True

def hunt_de_backup():
    nodes = get_nodes()
    de_node = [n for n in nodes["nodes"] if n["id"] == "de"][0]
    cur_pool = json.loads(fetch(REPO + "/de-pool.json"))
    xray = setup_xray()
    active_ok = 0
    for t in range(2):
        r = test(xray, {"server": cur_pool[0]["h"], "port": int(cur_pool[0]["p"]),
                        "cipher": "aes-128-gcm" if cur_pool[0]["kl"] == "16" else "aes-256-gcm",
                        "password": cur_pool[0]["k"]}, 15990, speed=False)
        if r and r.get("exit", "").startswith("DE"): active_ok += 1
    print(f"عضو فعلی آلمان: {active_ok}/2")
    if active_ok >= 2:
        print("آلمان سالم — نجات لازم نیست")
        return False
    cands = []
    for url, src in [
        ("https://cdn.jsdelivr.net/gh/xiaoji235/airport-free/v2ray.txt", "airport"),
        ("https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/master/sub/proxies.txt", "mahdi0024"),
        ("https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2", "v2rayfree"),
        ("https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/refs/heads/main/configs/proxy_configs.txt", "anonymou3")]:
        try: parse_ss(fetch(url), src, cands)
        except Exception as e: print("منبع:", str(e)[:40])
    cm = geo_batch(sorted({c["server"] for c in cands}))
    de = [c for c in cands if cm.get(c["server"], ("", ""))[0] == "DE"
          and not (c["server"] == cur_pool[0]["h"] and str(c["port"]) == str(cur_pool[0]["p"]))]
    print("کاندید جایگزین آلمان:", len(de))
    best = None
    for i, n in enumerate(de[:12]):
        ok = 0
        for t in range(2):
            r = test(xray, n, 15960 + t, speed=True)
            if r and r.get("exit", "").startswith("DE") and r.get("down", 0) > 700: ok += 1
        if ok >= 2: best = n; break
    if not best:
        print("جایگزین آلمانی پیدا نشد — عضو فعلی می‌ماند")
        return False
    new_pool = [{"n": f"de-{(best.get('exit') or 'de').split(':')[-1].lower()}-{best['server']}",
                 "h": best["server"], "p": str(best["port"]), "k": best["password"],
                 "kl": "16" if best["cipher"] == "aes-128-gcm" else "32"}] + cur_pool
    line = line_of(gist_files()["de.txt"], de_node["host"])
    uuid = uuid_from_line(line)
    deploy_worker(de_node["worker"], uuid, "de", new_pool, "de-acc1")
    cf_api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/d1/database/{D1}/query",
           body={"sql": "INSERT INTO active_srv (id, name, updated) VALUES ('de', ?1, datetime('now')) "
                        "ON CONFLICT(id) DO UPDATE SET name = ?1, updated = datetime('now')",
                 "params": [new_pool[0]["n"]]})
    put_repo("de-pool.json", json.dumps(new_pool, indent=1), "de rescue: new active member")
    print("✅ نجات آلمان: عضو نو فعال شد:", new_pool[0]["n"])
    return True

def main():
    import datetime
    report = {"checked_at": datetime.datetime.utcnow().isoformat() + "Z", "counts": {}, "stable": {}, "enabled": [], "refreshed": [], "de_rescue": None}
    counts = harvest(["NL", "FR", "GB"])
    report["counts"] = {cc: len(v) for cc, v in counts.items()}
    xray = setup_xray()
    enabled = {n["id"].upper() for n in get_nodes()["nodes"]}
    for cc, cands in counts.items():
        good = []
        for i, n in enumerate(cands[:10]):
            try: r = test(xray, n, 16100 + (i % 35), speed=True)
            except Exception: continue
            if r["exit"].startswith(cc) and r["down"] > 700:
                ok = 0
                for t in range(2):
                    rr = test(xray, n, 16500 + t, speed=True)
                    if rr["exit"].startswith(cc) and rr["down"] > 700: ok += 1
                if ok >= 2: good.append(r); print(f"پایدار ✅ {cc} {n['server']}:{n['port']}")
        report["stable"][cc] = len(good)
        if len(good) >= 2:
            try:
                if cc in enabled:
                    if refresh_pool(cc, good): report["refreshed"].append(cc)
                elif enable_country(cc, good):
                    report["enabled"].append(cc)
            except Exception as e:
                report.setdefault("errors", []).append(f"{cc}: {str(e)[:140]}")
                print(f"خطای فعال‌سازی {cc}:", str(e)[:120])
    try:
        if hunt_de_backup(): report["de_rescue"] = "activated"
    except Exception as e:
        report["de_rescue"] = ("err: " + str(e))[:120]
        report.setdefault("errors", []).append("de_rescue: " + str(e)[:140])
    put_repo("hunt-status.json", json.dumps(report, ensure_ascii=False, indent=1), "hunt report")
    print("گزارش:", json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
