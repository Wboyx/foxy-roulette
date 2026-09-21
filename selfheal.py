#!/usr/bin/env python3
# نگهبان خودترمیم چندلوکیشنی — درجه ۳ (چک هر ۵ دقیقه)
# هر نود: تست خروجی واقعی (۳ تلاش) → زنده: ثبت / مُرده: حذف+ساخت نام نو+فعال‌سازی+پیچ gist+تأیید
import os, json, time, base64, urllib.request, urllib.parse, subprocess, threading, datetime

GH = os.environ["GIST_TOKEN"]
CF = os.environ["CF_API_TOKEN"]
STATE = json.load(open("de-nodes.json"))
NODES = STATE["nodes"] if "nodes" in STATE else [STATE]   # سازگاری با ساختار قدیمی
BASE_PORT = 11740

def api(url, method="GET", body=None, token=GH):
    if token == GH:
        headers = {"Authorization": "token " + token, "content-type": "application/json"}
    else:
        headers = {"Authorization": "Bearer " + token, "content-type": "application/json"}
    req = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=40))

def test_alive(node, port):
    node_uuid, node_host = gist_conn(node)
    def run_bridge():
        try:
            subprocess.run(["python3", "-u", "vless_bridge.py", node_uuid, str(port), node_host],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=150)
        except Exception:
            pass
    threading.Thread(target=run_bridge, daemon=True).start()
    time.sleep(4)
    result = {"alive": False, "attempts": 3}
    for attempt in range(3):
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10",
            "--socks5-hostname", f"127.0.0.1:{port}",
            "https://www.gstatic.com/generate_204"], capture_output=True, text=True)
        if r.stdout.strip() == "204":
            result = {"alive": True, "attempts": attempt + 1}
            break
        time.sleep(4)
    return result

def gist_conn(node):
    """(uuid, host) نود را از خطش در gist می‌خواند — ریپو هرگز uuid/host قطعی ندارد."""
    gist = api(f"https://api.github.com/gists/{node['gist']}")
    content = gist["files"][node["gist_file"]]["content"]
    flag = urllib.parse.quote(node["label"][:2])
    for l in content.splitlines():
        if l.startswith("vless://") and flag in l:
            return l[8:].split("@")[0], l.split("@")[1].split(":")[0]
    raise RuntimeError(f"خط gist برای {node['label']} پیدا نشد")

def repair(node):
    node_uuid, _old_host = gist_conn(node)
    # ۱) حذف ورکر خراب
    try:
        api(f"https://api.cloudflare.com/client/v4/accounts/{node['account']}/workers/scripts/{node['worker']}",
            "DELETE", token=CF)
        print("حذف:", node["worker"])
    except Exception as e:
        print("حذف (نادیده):", str(e)[:100])
    # ۲) ساخت با نام تازه (subdomain نو = پادزهر فیلتر دامنه هم هست)
    stamp = str(int(time.time()))[-6:]
    prefix = node.get("prefix", "foxy-de")
    new_name = f"{prefix}-{stamp}"
    new_host = f"{new_name}.mahdi-wz10.workers.dev"
    boundary = "----foxy" + stamp
    code = open("de-worker.js", "rb").read()
    node_pool = json.load(open(node.get("pool_file", "de-pool.json")))
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": node_uuid},
              {"type": "plain_text", "name": "WNAME", "text": node.get("id", "de") + "-acc1"},
              {"type": "plain_text", "name": "SRV_ID", "text": node.get("srv_id", node.get("id", "de"))},
              {"type": "plain_text", "name": "SS_POOL", "text": json.dumps(node_pool)},
              {"type": "d1", "name": "DB", "id": node["d1"]}]}
    body = (f"--{boundary}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"metadata.json\"\r\n"
            f"content-type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"worker.js\"\r\n"
            f"content-type: application/javascript+module\r\n\r\n").encode() + code + \
           f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{node['account']}/workers/scripts/{new_name}",
        data=body, method="PUT",
        headers={"Authorization": "Bearer " + CF,
                 "content-type": f"multipart/form-data; boundary={boundary}"})
    up = json.load(urllib.request.urlopen(req, timeout=90))
    assert up.get("success"), f"ساخت ناموفق: {str(up)[:200]}"
    print("ساخت:", new_name, "✅")
    # ۳) workers.dev روشن (ورکر نو پیش‌فرض خاموش است — درس ۱۰۴۲)
    api(f"https://api.cloudflare.com/client/v4/accounts/{node['account']}/workers/scripts/{new_name}/subdomain",
        "POST", {"enabled": True}, token=CF)
    # ۴) پیچ gist — همان UUID و برچسب، فقط میزبان نو
    q = urllib.parse.urlencode({"encryption": "none", "security": "tls", "sni": new_host, "fp": "chrome",
                                "type": "ws", "host": new_host, "path": "/" + node_uuid, "alpn": "http/1.1"})
    new_line = f"vless://{node_uuid}@{new_host}:443?{q}#{urllib.parse.quote(node['label'])}"
    gist = api(f"https://api.github.com/gists/{node['gist']}")
    content = gist["files"][node["gist_file"]]["content"]
    lines = [l for l in content.splitlines() if l.strip()]
    replaced = False
    for i, l in enumerate(lines):
        if f"@{node['host']}:" in l and l.startswith("vless://"):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    api(f"https://api.github.com/gists/{node['gist']}", "PATCH",
        {"files": {node["gist_file"]: {"content": "\n".join(lines)}}})
    print("gist پیچ شد (line-aware) ✅")
    sync_nodes_file()
    redeploy_watch()
    node["worker"], node["host"] = new_name, new_host
    return new_name, new_host


def sync_nodes_file():
    """de-nodes.json را از gist بازسازی می‌کند (worker/host همیشه واقعی)."""
    gist = api("https://api.github.com/gists/13263cbf8ac3342eb6333825fcab2249")
    content = gist["files"]["de.txt"]["content"]
    flagmap = {"\U0001F1E9\U0001F1EA": "de2", "\U0001F1FA\U0001F1F8": "us", "\U0001F1EC\U0001F1E7": "gb",
               "\U0001F1F3\U0001F1F1": "nl", "\U0001F1EB\U0001F1F7": "fr", "\U0001F1E8\U0001F1E6": "ca",
               "\U0001F1F8\U0001F1EC": "sg", "\U0001F1EF\U0001F1F5": "jp", "\U0001F1E8\U0001F1ED": "ch",
               "\U0001F1F8\U0001F1EA": "se", "\U0001F1E6\U0001F1F9": "at", "\U0001F1F9\U0001F1F7": "tr",
               "\U0001F1E6\U0001F1EA": "ae", "\U0001F1F7\U0001F1FA": "ru", "\U0001F1F5\U0001F1F1": "pl",
               "\U0001F1EE\U0001F1F9": "it", "\U0001F1EB\U0001F1EE": "fi"}
    nodes = []
    for l in content.splitlines():
        if not l.startswith("vless://"): continue
        try: label = urllib.parse.unquote(l.split("#")[1] or "")
        except Exception: continue
        cid = flagmap.get(label[:2])
        if not cid: continue
        host = l.split("@")[1].split(":")[0]
        nodes.append({"id": cid, "prefix": "foxy-" + cid, "worker": host.split(".")[0], "host": host, "label": label,
                      "srv_id": cid, "pool_file": (None if cid == "de2" else f"{cid}-pool.json"), "gist_file": "de.txt",
                      "gist": "13263cbf8ac3342eb6333825fcab2249",
                      "d1": "3dccbbba-1f23-4664-9803-845e985663b8",
                      "account": "ee9234f9f2ba43105901dffc624d696d"})
    payload = {"message": "sync nodes from gist (post-repair)",
               "content": base64.b64encode(json.dumps({"nodes": nodes}, indent=1).encode()).decode()}
    try:
        cur = api("https://api.github.com/repos/Wboyx/foxy-roulette/contents/de-nodes.json")
        if "sha" in cur: payload["sha"] = cur["sha"]
    except Exception: pass
    api("https://api.github.com/repos/Wboyx/foxy-roulette/contents/de-nodes.json", "PUT", payload)
    return nodes

def redeploy_watch():
    """نگهبان را با bindingهای نو سیم‌کشی می‌کند (بعد از هر ترمیم)."""
    import uuid as ul
    nodes = sync_nodes_file()
    code = open("foxy-watch.js", "rb").read()
    try:
        gist = api("https://api.github.com/gists/13263cbf8ac3342eb6333825fcab2249")
        key = gist["files"]["watch.txt"]["content"].strip()
    except Exception:
        key = open("watch-key.txt").read().strip()
    bindings = [
        {"type": "plain_text", "name": "KEY", "text": key},
        {"type": "secret_text", "name": "GH", "text": GH},
        {"type": "plain_text", "name": "GIST_RAW",
         "text": "https://gist.githubusercontent.com/Wboyx/13263cbf8ac3342eb6333825fcab2249/raw/de.txt"},
        {"type": "plain_text", "name": "NODE_IDS", "text": ",".join(n["id"] for n in nodes)},
        {"type": "d1", "name": "DB", "id": "3dccbbba-1f23-4664-9803-845e985663b8"}]
    for n in nodes:
        bindings.append({"type": "service", "name": "S_" + n["id"].upper(),
                         "service": n["worker"], "environment": "production"})
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": bindings, "schedules": [{"cron": "*/5 * * * *"}]}
    b = str(ul.uuid4())
    body = (f"--{b}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"m.json\"\r\n"
            f"content-type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{b}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"worker.js\"\r\n"
            f"content-type: application/javascript+module\r\n\r\n").encode() + code + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/accounts/ee9234f9f2ba43105901dffc624d696d/workers/scripts/foxy-watch",
        method="PUT", data=body,
        headers={"Authorization": "Bearer " + CF, "content-type": f"multipart/form-data; boundary={b}"})
    out = json.load(urllib.request.urlopen(req, timeout=90))
    print("نگهبان بازسیم شد:", out.get("success"))

def main():
    # گارد: بدون ابزار تست هرگز چیزی را حذف نکن (ضد false-negative)
    for f in ("vless_bridge.py", "de-worker.js", "foxy-watch.js"):
        if not os.path.exists(f):
            raise SystemExit(f"فایل {f} نیست — لغو کامل (هیچ حذفی انجام نشد)")
    for node in NODES:
        pf = node.get("pool_file")
        if pf and not os.path.exists(pf):
            raise SystemExit(f"استخر {pf} نیست — لغو کامل (هیچ حذفی انجام نشد)")
    out = {"checked_at": datetime.datetime.utcnow().isoformat() + "Z", "nodes": {}}
    dirty = False
    for i, node in enumerate(NODES):
        nid = node.get("id", f"node{i}")
        port = BASE_PORT + i * 2
        r1 = test_alive(node, port)
        entry = {**r1, "worker": node["worker"], "host": node["host"]}
        if r1["alive"]:
            print(f"{nid}: زنده ✅ (تلاش {r1['attempts']})")
        else:
            print(f"{nid}: مُرده — خودترمیم…")
            new_name, new_host = repair(node)
            r2 = test_alive(node, port + 1)          # باگ‌فیکس: پورت پل نو برای تستِ نو
            entry.update({"repaired": True, "new_worker": new_name, "new_host": new_host,
                          "repair_alive": r2["alive"], "repair_attempts": r2["attempts"]})
            dirty = True
            print(f"{nid}: ترمیم {'✅ تأیید' if r2['alive'] else '❌ ناموفق — بررسی دستی'}")
        out["nodes"][nid] = entry
    json.dump(STATE, open("de-nodes.json", "w"), ensure_ascii=False, indent=1)
    json.dump(out, open("health-status.json", "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
