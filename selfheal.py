#!/usr/bin/env python3
# نگهبان خودترمیم چندلوکیشنی — درجه ۳ (چک هر ۵ دقیقه)
# هر نود: تست خروجی واقعی (۳ تلاش) → زنده: ثبت / مُرده: حذف+ساخت نام نو+فعال‌سازی+پیچ gist+تأیید
import os, json, time, base64, urllib.request, urllib.parse, subprocess, threading, datetime

GH = os.environ["GIST_TOKEN"]
CF = os.environ["CF_API_TOKEN"]
STATE = json.load(open("de-nodes.json"))
NODES = STATE["nodes"] if "nodes" in STATE else [STATE]   # سازگاری با ساختار قدیمی
POOL = json.load(open("de-pool.json"))
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
    def run_bridge():
        try:
            subprocess.run(["python3", "-u", "vless_bridge.py", node["uuid"], str(port), node["host"]],
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

def repair(node):
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
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": node["uuid"]},
              {"type": "plain_text", "name": "WNAME", "text": node.get("id", "de") + "-acc1"},
              {"type": "plain_text", "name": "SS_POOL", "text": json.dumps(POOL)},
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
                                "type": "ws", "host": new_host, "path": "/" + node["uuid"], "alpn": "http/1.1"})
    content = f"vless://{node['uuid']}@{new_host}:443?{q}#{urllib.parse.quote(node['label'])}"
    api(f"https://api.github.com/gists/{node['gist']}", "PATCH",
        {"files": {node["gist_file"]: {"content": content}}})
    print("gist پیچ شد ✅")
    node["worker"], node["host"] = new_name, new_host
    return new_name, new_host

def main():
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
