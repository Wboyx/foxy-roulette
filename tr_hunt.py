#!/usr/bin/env python3
# tr_hunt — شکارچی ترکیه (چندپروتکلی): برداشت تازه → فیلتر جغرافیا → اعتبارسنجی TLS → نوشتن gist tr.txt
# خروجی فقط «کاندید زنده» است؛ تأیید نهایی = تست گوشی کاربر از ایران (ساب تست).
import os, re, json, time, html, base64, socket, ssl, urllib.parse
import requests

GH = os.environ.get("GIST_TOKEN", "")
GIST = os.environ.get("GIST_ID", "13263cbf8ac3342eb6333825fcab2249")
S = requests.Session()
S.headers["user-agent"] = "foxy-tr-hunt/1.0"

CAND = {}

def add(uri, src):
    try:
        u = uri.strip()
        if u.startswith(("vless://", "trojan://")):
            scheme = u.split("://")[0]
            body = u[len(scheme) + 3:].split("#")[0]
            uid, rest = body.split("@", 1)
            h = rest.split(":")[0]
            p = rest.split(":")[1].split("?")[0]
            CAND.setdefault((h, p), {"uri": u, "src": src})
        elif u.startswith("vmess://"):
            j = json.loads(base64.b64decode(u[8:] + "===").decode(errors="ignore"))
            CAND.setdefault((str(j.get("add", "")), str(j.get("port", ""))), {"uri": u, "src": src})
    except Exception:
        pass

def fetch(url, timeout=40):
    try:
        return S.get(url, timeout=timeout).text
    except Exception:
        return ""

def harvest():
    # مخازن (base64/متنی)
    for url in ["https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
                "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vmess.txt",
                "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/trojan.txt",
                "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt"]:
        t = fetch(url)
        if not t: continue
        try:
            t = base64.b64decode(t + "===").decode(errors="ignore")
        except Exception:
            pass
        for l in t.splitlines():
            l = html.unescape(l.strip())
            if l[:8] in ("vless://", "trojan:/", "vmess:/"):
                add(l, "repo")
    # تلگرام (تازه‌ترین‌ها)
    for ch in ("V2rayConfigList", "ev2rayy", "v2ray_youtube", "v2rayuir"):
        t = html.unescape(fetch(f"https://t.me/s/{ch}"))
        for l in re.findall(r"(?:vless|trojan|vmess)://[^\s<\"']+@[\w\.\-]+:\d+\?[^\s<\"']+", t):
            add(l, "tg")
    return len(CAND)

def is_cf(ip):
    return re.fullmatch(r"(104\.(1[6-9]|2[0-7])|172\.(6[4-9]|7[01])|188\.114|162\.159|198\.41|141\.101|190\.93|103\.2[1-8])\..*", ip or "")

def geo_tr():
    out, cache = [], {}
    for (h, p), v in CAND.items():
        if h.count(".") != 3 or is_cf(h): continue
        if h not in cache:
            try:
                cache[h] = S.get(f"http://ip-api.com/json/{h}?fields=countryCode", timeout=8).json().get("countryCode", "??")
            except Exception:
                cache[h] = "??"
            time.sleep(1.1)
        if cache[h] == "TR":
            out.append({**v, "h": h, "p": p})
    return out

def tls_alive(h, p, sni):
    """سرور reality/tls موظف است برای ClientHello جواب بدهد — جواب = زنده."""
    try:
        s = socket.create_connection((h, int(p)), timeout=7)
        s.settimeout(7)
        if sni:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=sni)
            # TLS برقرار شد = سرور پاسخ handshake داد
        s.close()
        return True
    except ssl.SSLError:
        return True   # پاسخ TLS (حتی alert) = پورت زندهٔ TLS؛ اپ‌لایه را کلاینت واقعی می‌سنجد
    except Exception:
        return False

def main():
    n = harvest()
    print(f"برداشت: {n} کاندید یکتا")
    trs = geo_tr()
    print(f"کاندید TR: {len(trs)}")
    alive = []
    seen = set()
    for c in trs:
        key = (c["h"], c["p"])
        if key in seen: continue
        seen.add(key)
        u = c["uri"]
        sni = ""
        if u.startswith(("vless://", "trojan://")):
            try:
                q = urllib.parse.parse_qs(u.split("?")[1].split("#")[0], keep_blank_values=True)
                sni = q.get("sni", [""])[0] or (q.get("host", [""])[0])
            except Exception:
                pass
        if tls_alive(c["h"], c["p"], sni):
            alive.append(c)
    print(f"زندهٔ TLS: {len(alive)}")
    # حفظ خطوط آلمان (تأییدشده با هندشیک TLS) — tr_hunt فقط TRها را مدیریت می‌کند
    keep_de = []
    try:
        old_txt = requests.get(f"https://gist.githubusercontent.com/Wboyx/{GIST}/raw/tr.txt", timeout=20).text
        for l in old_txt.splitlines():
            frag = l.split("#")[1] if "#" in l else ""
            if l.startswith(("vless://", "trojan://")) and "Germany" in urllib.parse.unquote(frag):
                keep_de.append(l)
    except Exception:
        pass
    lines = [f"# tr.txt — کاندیدهای ترکیه + آلمان (تولید خودکار tr_hunt) — {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"] + keep_de
    # حفظ خطوط قدیمی هنوز-زنده در سرِ فهرست (پایداری برچسب T1/T2/... — BUGLOG قاعده: برچسب ثابت مشتری)
    def host_of(line):
        try: return line.split("://", 1)[1].split("#")[0].split("?")[0].rsplit("@", 1)[1].rsplit(":", 1)[0]
        except Exception: return ""
    def port_of(line):
        try: return line.split("://", 1)[1].split("#")[0].split("?")[0].rsplit(":", 1)[1]
        except Exception: return ""
    alive_hosts = {(c["h"], c["p"]) for c in alive}
    pinned = []
    try:
        for l in old_txt.splitlines():
            if l.startswith(("vless://", "trojan://")) and "Germany" not in urllib.parse.unquote(l.split("#")[1] if "#" in l else ""):
                if (host_of(l), port_of(l)) in alive_hosts and l not in pinned:
                    pinned.append(l)
    except Exception:
        pass
    lines += pinned
    used = {(host_of(l), port_of(l)) for l in pinned}
    i = len(pinned)
    for c in alive:
        if (c["h"], c["p"]) in used: continue
        i += 1
        label = urllib.parse.quote(f"🇹🇷 Turkey 🦊 T{i}")
        clean = c["uri"].split("#")[0]
        lines.append(f'{clean}#{label}')
    if not alive:
        lines.append("# هیچ کاندید زندهٔ TR در این دور")
    content = "\n".join(lines) + "\n"
    r = requests.patch(f"https://api.github.com/gists/{GIST}",
        headers={"Authorization": f"token {GH}"},
        json={"files": {"tr.txt": {"content": content}}}, timeout=30)
    print("gist tr.txt:", "✅" if r.status_code == 200 else r.status_code)

if __name__ == "__main__":
    main()
