#!/usr/bin/env python3
# نگهبان خودترمیم گره آلمان — درجه ۳
# هر اجرا: تست خروجی واقعی → زنده: ثبت وضعیت / مُرده (۳ تلاش): حذف+ساخت نام نو+فعال‌سازی+پیچ gist+ثبت
import os, json, time, base64, urllib.request, urllib.parse, subprocess, threading, datetime

GH = os.environ["GIST_TOKEN"]
CF = os.environ["CF_API_TOKEN"]
STATE = json.load(open("de-nodes.json"))
POOL = json.load(open("de-pool.json"))
PORT = "11730"
ACC = STATE["account"]

def api(url, method="GET", body=None, token=GH, ct="application/json"):
    req = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "token " + token, "Authorization-Bearer": token,
                 "content-type": ct} if token == GH else
                {"Authorization": "Bearer " + token, "content-type": ct})
    return json.load(urllib.request.urlopen(req, timeout=40))

def test_alive():
    # پل WS → curl سه‌تلاشی
    def run_bridge():
        subprocess.run(["python3", "-u", "vless_bridge.py", STATE["uuid"], PORT, STATE["host"]],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    threading.Thread(target=run_bridge, daemon=True).start()
    time.sleep(4)
    for attempt in range(3):
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10",
            "--socks5-hostname", f"127.0.0.1:{PORT}",
            "https://www.gstatic.com/generate_204"], capture_output=True, text=True)
        if r.stdout.strip() == "204":
            return True, attempt + 1
        time.sleep(4)
    return False, 3

def repair():
    # ۱) حذف ورکر خراب (بی‌خیال خطا)
    try:
        api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/{STATE['worker']}",
            "DELETE", token=CF)
        print("حذف:", STATE["worker"])
    except Exception as e:
        print("حذف (خطا نادیده):", str(e)[:100])
    # ۲) نام تازه
    stamp = str(int(time.time()))[-6:]
    new_name = f"foxy-de-{stamp}"
    new_host = f"{new_name}.mahdi-wz10.workers.dev"
    boundary = "----foxy" + stamp
    code = open("de-worker.js", "rb").read()
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-23",
            "bindings": [
              {"type": "plain_text", "name": "UUID", "text": STATE["uuid"]},
              {"type": "plain_text", "name": "WNAME", "text": "de-acc1"},
              {"type": "plain_text", "name": "SS_POOL", "text": json.dumps(POOL)},
              {"type": "d1", "name": "DB", "id": STATE["d1"]}]}
    body = (f"--{boundary}\r\ncontent-disposition: form-data; name=\"metadata\"; filename=\"metadata.json\"\r\n"
            f"content-type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\ncontent-disposition: form-data; name=\"worker.js\"; filename=\"worker.js\"\r\n"
            f"content-type: application/javascript+module\r\n\r\n").encode() + code + \
           f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/{new_name}",
        data=body, method="PUT",
        headers={"Authorization": "Bearer " + CF,
                 "content-type": f"multipart/form-data; boundary={boundary}"})
    up = json.load(urllib.request.urlopen(req, timeout=90))
    assert up.get("success"), up
    print("ساخت:", new_name, "✅")
    # ۳) workers.dev روشن:
    api(f"https://api.cloudflare.com/client/v4/accounts/{ACC}/workers/scripts/{new_name}/subdomain",
        "POST", {"enabled": True}, token=CF)
    # ۴) پیچ gist (همان UUID و نام — فقط میزبان نو):
    q = urllib.parse.urlencode({"encryption": "none", "security": "tls", "sni": new_host, "fp": "chrome",
                                "type": "ws", "host": new_host, "path": "/" + STATE["uuid"], "alpn": "http/1.1"})
    content = f"vless://{STATE['uuid']}@{new_host}:443?{q}#{urllib.parse.quote(STATE['label'])}"
    api(f"https://api.github.com/gists/{STATE['gist']}", "PATCH",
        {"files": {STATE["gist_file"]: {"content": content}}})
    print("gist پیچ شد ✅")
    return new_name, new_host

def main():
    alive, attempts = test_alive()
    out = {"checked_at": datetime.datetime.utcnow().isoformat() + "Z",
           "worker": STATE["worker"], "host": STATE["host"], "alive": alive, "attempts": attempts}
    if alive:
        print("گره زنده است ✅")
    else:
        print("گره مُرده — خودترمیم شروع می‌شود…")
        new_name, new_host = repair()
        # تأیید ترمیم با تست دوباره:
        STATE["worker"], STATE["host"] = new_name, new_host
        json.dump(STATE, open("de-nodes.json", "w"), indent=1)
        alive2, att2 = test_alive()
        out.update({"repaired": True, "new_worker": new_name, "new_host": new_host,
                    "repair_verified": alive2, "repair_attempts": att2})
        print("ترمیم:", "✅ تأیید شد" if alive2 else "❌ هنوز خراب — بررسی دستی لازم")
    json.dump(out, open("health-status.json", "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
