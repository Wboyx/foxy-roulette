// 🦊 نسخهٔ تک‌فایلی — نود با /geo و /exit

// ═══ foxy-sub/vless-core.js — منطق خالص VLESS (بدون وابستگی به runtime کلادفلر) ═══
// هم برای ورکرها import می‌شود هم برای تست‌های node — تک‌منبع حقیقت.

const enc = new TextEncoder();

// ── تجزیهٔ بایت‌های درخواست VLESS (ISO مستقل از transport) ──
// [ver(1)][uuid(16)][addonLen(1)][addon][cmd(1)][port(2)BE][atyp(1)][addr][payload]
function parseVlessRequest(u8) {
  if (!u8 || u8.length < 25) return null;
  if (u8[0] !== 0) return null;
  const uuid = toHex(u8.slice(1, 17));
  const addonLen = u8[17];
  let p = 18 + addonLen;
  if (u8.length < p + 4) return null;
  const cmd = u8[p];                      // 1=tcp 2=udp 3=mux
  const port = (u8[p + 1] << 8) | u8[p + 2];
  const atyp = u8[p + 3];
  p += 4;
  let host = "";
  if (atyp === 1) {                       // IPv4
    if (u8.length < p + 4) return null;
    host = Array.from(u8.slice(p, p + 4)).join(".");
    p += 4;
  } else if (atyp === 2) {                // دامنه
    const len = u8[p];
    if (u8.length < p + 1 + len) return null;
    host = new TextDecoder().decode(u8.slice(p + 1, p + 1 + len));
    p += 1 + len;
  } else if (atyp === 3) {                // IPv6
    if (u8.length < p + 16) return null;
    const b = u8.slice(p, p + 16); p += 16;
    const parts = [];
    for (let i = 0; i < 16; i += 2) parts.push(((b[i] << 8) | b[i + 1]).toString(16));
    host = parts.join(":");
  } else return null;
  return { uuid, cmd, port, host, atyp, payloadOffset: p };
}

function toHex(buf) {
  return Array.from(buf).map(b => b.toString(16).padStart(2, "0")).join("");
}
function fromHex(s) {
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(i * 2, i * 2 + 2), 16);
  return out;
}

// جواب سرور VLESS: [ver=0][addonLen=0]
function vlessResponseHeader() {
  return new Uint8Array([0, 0]);
}

// ── چیدمان نودها از متغیرهای محیطی ──
// WORKERS: هر خط "name|host|uuid"
// NODES_URL یا NODES: هر خط "ip|port" (IPهای تمیز ورودی TLS کلادفلر) — خالی یعنی خود هاست ورکر
function buildNodes(workersTxt, entriesTxt, opts = {}) {
  const workers = String(workersTxt || "").split("\n").map(l => l.trim())
    .filter(l => l && !l.startsWith("#"))
    .map(l => {
      const [name, host, uuid] = l.split("|").map(s => s.trim());
      return { name, host, uuid };
    })
    .filter(w => w.host && w.uuid);
  let entries = String(entriesTxt || "").split("\n").map(l => l.trim())
    .filter(l => l && !l.startsWith("#"))
    .map(l => {
      const [ip, port] = l.split("|").map(s => s.trim());
      return { ip, port: parseInt(port || "443", 10) || 443 };
    });
  if (!entries.length) entries = [[443], [2053], [2083], [2087], [2096], [8443]].map(([p]) => ({ ip: "", port: p }));
  const FLAGS = ["🇺🇸", "🇩🇪", "🇳🇱", "🇫🇷", "🇬🇧", "🇹🇷", "🇮🇹", "🇯🇵", "🇸🇬", "🇨🇦", "🇦🇺", "🇰🇷", "🇪🇸", "🇨🇭", "🇸🇪", "🇳🇴", "🇫🇮", "🇩🇰", "🇦🇹", "🇮🇪", "🇧🇪", "🇵🇹", "🇵🇱", "🇨🇿"];
  const nodes = [];
  for (const w of workers) {
    entries.forEach((e, i) => {
      const address = e.ip || w.host;
      const flag = FLAGS[nodes.filter(x => x.wname === w.name).length % FLAGS.length];
      const n = (opts.maxPerWorker && nodes.filter(x => x.wname === w.name).length >= opts.maxPerWorker)
        ? null
        : {
            wname: w.name,
            name: `${flag} ${w.name}${entries.length > 1 ? ` ▸ ${String(i + 1).padStart(2, "0")}` : ""}`,
            address, port: e.port,
            host: w.host, uuid: w.uuid,
            path: `/${w.uuid}`,
            sni: w.host,
          };
      if (n) nodes.push(n);
    });
  }
  return nodes;
}

// ── سازنده‌های سه فرمت ──
function vlessUri(n) {
  const q = new URLSearchParams({
    encryption: "none", security: "tls", sni: n.sni, fp: "chrome",
    host: n.host, type: "ws", path: n.path,
  });
  return `vless://${n.uuid}@${n.address}:${n.port}?${q.toString()}#${encodeURIComponent(n.name)}`;
}

function infoNodeUri(text) {
  const q = new URLSearchParams({
    encryption: "none", security: "none", type: "ws", path: "/info", host: "127.0.0.1",
  });
  return `vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1?${q.toString()}#${encodeURIComponent(text)}`;
}

function toB64Sub(uris) {
  return btoa(uris.join("\n"));
}

function singboxOutbound(n) {
  return {
    type: "vless", tag: n.name, server: n.address, server_port: n.port,
    uuid: n.uuid,
    tls: { enabled: true, server_name: n.sni, utls: { enabled: true, fingerprint: "chrome" } },
    transport: { type: "ws", path: n.path, headers: { Host: n.host } },
  };
}

const yq = s => `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
function clashProxy(n) {
  return {
    name: n.name, type: "vless", server: n.address, port: n.port, uuid: n.uuid,
    udp: true, tls: true, servername: n.sni, "client-fingerprint": "chrome", network: "ws",
    "ws-opts": { path: n.path, headers: { Host: n.host } },
  };
}
function clashYaml(nodes, infoLines = []) {
  const names = nodes.map(n => n.name);
  const L = [];
  L.push("mode: rule");
  L.push("log-level: warning");
  L.push("proxies:");
  for (const n of nodes) {
    L.push(`  - name: ${yq(n.name)}`);
    L.push(`    type: vless`);
    L.push(`    server: ${n.address}`);
    L.push(`    port: ${n.port}`);
    L.push(`    uuid: ${n.uuid}`);
    L.push(`    udp: true`);
    L.push(`    tls: true`);
    L.push(`    servername: ${n.sni}`);
    L.push(`    client-fingerprint: chrome`);
    L.push(`    network: ws`);
    L.push(`    ws-opts:`);
    L.push(`      path: ${yq(n.path)}`);
    L.push(`      headers:`);
    L.push(`        Host: ${n.host}`);
  }
  L.push("proxy-groups:");
  L.push(`  - name: ${yq("🦊 فاکسی-اتو")}`);
  L.push("    type: url-test");
  L.push("    url: https://www.gstatic.com/generate_204");
  L.push("    interval: 300");
  L.push(`    proxies:`);
  for (const nm of names) L.push(`      - ${yq(nm)}`);
  L.push("rules:");
  L.push("    - MATCH,🦊 فاکسی-اتو");
  return L.join("\n") + "\n";
}

// ── تشخیص اپ از روی User-Agent (+ پارامتر صریح) ──
function pickFormat(ua = "", search = "") {
  const u = String(ua).toLowerCase();
  if (/[?&](sb|singbox)\b/.test(search)) return "sb";
  if (/[?&](clash|yaml)\b/.test(search)) return "clash";
  if (/[?&](b64|base64|v2ray)\b/.test(search)) return "b64";
  if (/sing-box|sfi|sfa|sfm|sft|karing|nekobox|nekoray|hiddify/.test(u)) {
    // Hiddify و Nekobox هر دو b64 هم می‌فهمند؛ sing-box خالص sb می‌خواهد
    if (/hiddify|nekobox|nekoray/.test(u)) return "b64";
    return "sb";
  }
  if (/clash|mihomo|meta|stash/.test(u)) return "clash";
  if (/mozilla|chrome|safari|firefox|edge|iphone|ipad|android/.test(u)) return "html";
  return "b64";
}

// صفحهٔ کوچک مرورگر (وقتی لینک ساب در مرورگر باز شود)
function infoPage(title, lines, tokenPath) {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  return `<!doctype html><html dir=rtl lang=fa><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<body style="background:#141414;color:#f2e9df;font-family:Vazirmatn,Tahoma,sans-serif;display:flex;justify-content:center;padding:24px">
<div style="background:#1e1a16;border:1px solid #3a322a;border-radius:14px;padding:24px;max-width:420px;width:100%">
<h2 style="margin:0 0 8px;color:#e8722a">🦊 ${esc(title)}</h2>
<div style="font-size:13.5px;line-height:2">
${lines.map(l => "• " + esc(l)).join("<br>")}
</div>
<div style="margin-top:12px;font-size:12.5px;color:#b8a894">این لینک را در اپ (v2rayNG / Hiddify / Streisand / Clash) با «Add subscription» وارد کن — در مرورگر باز نکن.</div>
</div></body></html>`;
}

// ═══ foxy-sub/node-worker.js — نود VLESS+WS روی کلادفلر (تک‌فایل، بدون VPS) ═══
// متغیرهای لازم (Workers → Settings → Variables):
//   UUID    = یک uuid تصادفی (نمونه: openssl rand -hex 16 با خط‌های -)
//   PROXYIP = اختیاری؛ IP/دامنهٔ کلادفلری برای سایت‌هایی که خودشان پشت کلادفلرند
import { connect } from "cloudflare:sockets";


export default {
  async fetch(req, env) {
    const dashed = String(env.UUID || "").trim().toLowerCase();
    const uuid = dashed.replace(/-/g, "");
    const url = new URL(req.url);
    if (["/usage","/geo","/exit","/tcheck"].includes(url.pathname) && url.searchParams.get("key") !== dashed)
      return new Response("not found", { status: 404 });
    if (req.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      if (url.pathname === "/usage") {
        // ═══ شمارش ظرفیت (چرخش هوشمند اکانت‌ها): مصرف امروز هر ورکر ═══
        try {
          const rows = await env.DB.prepare(
            "SELECT worker, day, n FROM node_usage WHERE day = date('now')").all();
          const tot = (rows.results || []).reduce((s, r) => s + (r.n || 0), 0);
          let act = null;
          try { act = (await env.DB.prepare("SELECT name FROM active_srv WHERE id = ?").bind(String(env.SRV_ID || "de")).first() || {}).name || null; } catch {}
          return new Response(JSON.stringify({ day: new Date().toISOString().slice(0, 10),
            rows: rows.results || [], total_today: tot, quota_per_day: 100000, plan: "free",
            threshold_pct: 80, account: "acc1-mahdi-wz10", active_server: act,
            pool_size: JSON.parse(String(env.SS_POOL || "[]")).length }), {
            status: 200, headers: { "content-type": "application/json; charset=utf-8",
              "access-control-allow-origin": "*" } });
        } catch (e) {
          return new Response(JSON.stringify({ err: "error" }), { status: 500 });
        }
      }
      if (url.pathname === "/geo") {
        // کشور لبه‌ای که این کلاینت به آن وصل شد + مرکز داده — منبع: خود کلادفلر
        const ctry = req.cf && req.cf.country ? req.cf.country : "";
        const colo = req.cf && req.cf.colo ? req.cf.colo : "";
        return new Response(JSON.stringify({ country: ctry, colo }), {
          status: 200, headers: { "content-type": "application/json; charset=utf-8",
            "access-control-allow-origin": "*" },
        });
      }
      if (url.pathname === "/tcheck") {
        // سلامت واقعی تانل: اتصال SS به عضو از دل ورکر (نه فقط زنده‌بودن پروسه)
        const detail = [];
        try {
          const pool = JSON.parse(String(env.SS_POOL || "[]"));
          if (!pool.length) return new Response(JSON.stringify({ ok: false, why: "empty-pool" }),
            { status: 200, headers: { "content-type": "application/json" } });
          const act = await activeName(env).catch(() => null);
          const order = [...pool].sort((x, y) => (x.n === act ? -1 : (y.n === act ? 1 : 0)));
          for (const m of order.slice(0, 2)) {
            for (let attempt = 0; attempt < 2; attempt++) {
              try {
                const t0 = Date.now();
                const job = (async () => {
                  const c = connect({ hostname: m.h, port: parseInt(m.p, 10) });
                  const sess = (m.proto === "vless")
                    ? await vlessOpen(c, m, "ip-api.com", 80)
                    : await ssOpen(c, m, "ip-api.com", 80);
                  await sess.write(new TextEncoder().encode("GET /json/?fields=countryCode HTTP/1.1\r\nHost: ip-api.com\r\nConnection: close\r\n\r\n"));
                  const r = await sess.read();
                  try { c.close(); } catch {}
                  return r ? (r.length || (r.value && r.value.length) || 0) : 0;
                })();
                const n = await Promise.race([job, new Promise(res => setTimeout(() => res(-1), 6500))]);
                detail.push(m.n + ":" + (Date.now() - t0) + "ms:" + (n === -1 ? "هنگ" : n + "B"));
                if (n > 0) return new Response(JSON.stringify({ ok: true, member: m.n, ms: Date.now() - t0, detail }),
                  { status: 200, headers: { "content-type": "application/json" } });
              } catch (e) { detail.push(m.n + ":err:" + String(e && e.message || e).slice(0, 40)); }
            }
          }
          return new Response(JSON.stringify({ ok: false, detail }), { status: 200,
            headers: { "content-type": "application/json" } });
        } catch (e) {
          return new Response(JSON.stringify({ ok: false, why: String(e && e.message || e).slice(0, 60), detail }),
            { status: 200, headers: { "content-type": "application/json" } });
        }
      }
      if (url.pathname === "/exit") {
        // خروجی واقعی این نود: کلادفلر خودش می‌گوید ترافیک رفت از کدام کشور و با چه IP بیرون می‌رود
        try {
          const t = await (await fetch("https://www.cloudflare.com/cdn-cgi/trace",
            { headers: { "user-agent": "foxy-exit/1.0" } })).text();
          const g = k => (t.match(new RegExp("(?:^|\\n)" + k + "=(.*)")) || [])[1] || "";
          return new Response(JSON.stringify({ ip: g("ip"), colo: g("colo"), loc: g("loc") }),
            { status: 200, headers: { "content-type": "application/json; charset=utf-8",
              "access-control-allow-origin": "*" } });
        } catch {
          return new Response(JSON.stringify({}), { status: 502,
            headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });
        }
      }
      return new Response("not found", { status: 404 });
    }
    // مسیر باید /{UUID} باشد تا اسکنر تصادفی نتواند از نود سوءاستفاده کند
    if (!uuid || (url.pathname !== "/" + dashed && !url.pathname.startsWith("/" + dashed + "/"))) {
      return new Response("not found", { status: 404 });
    }
    let earlyData = null;
    const proto0 = (req.headers.get("sec-websocket-protocol") || "").split(",")[0].trim();
    if (proto0 && proto0.length > 16) {
      try {
        const bb = atob(proto0.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - proto0.length % 4) % 4));
        const u = new Uint8Array(bb.length);
        for (let i = 0; i < bb.length; i++) u[i] = bb.charCodeAt(i);
        if (u.length >= 20) earlyData = u;
      } catch {}
    }
    const pair = new WebSocketPair();
    serveWs(pair[1], uuid, env, earlyData).catch(() => { try { pair[1].close(); } catch {} });
    return new Response(null, { status: 101, webSocket: pair[0] });
  },
};


// ═══ کلاینت Shadowsocks-AEAD (SIP004) با WebCrypto — برای خروجی ثابت ═══
function b64ToU8(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
// ─── MD5 خالص (WebCrypto ندارد) — برای EVP_BytesToKey ───
function md5(bytes) {
  const S = [7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
  const K = new Uint32Array(64);
  for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);
  const len = bytes.length;
  const withPad = new Uint8Array((((len + 8) >> 6) + 1) << 6);
  withPad.set(bytes);
  withPad[len] = 0x80;
  new DataView(withPad.buffer).setUint32(withPad.length - 8, len << 3, true);
  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  const dv = new DataView(withPad.buffer);
  const rol = (x, c) => (x << c) | (x >>> (32 - c));
  for (let off = 0; off < withPad.length; off += 64) {
    const M = new Uint32Array(16);
    for (let i = 0; i < 16; i++) M[i] = dv.getUint32(off + i * 4, true);
    let A = a0, B = b0, C = c0, D = d0;
    for (let i = 0; i < 64; i++) {
      let F, g;
      if (i < 16)      { F = (B & C) | (~B & D);      g = i; }
      else if (i < 32) { F = (D & B) | (~D & C);      g = (5 * i + 1) & 15; }
      else if (i < 48) { F = B ^ C ^ D;               g = (3 * i + 5) & 15; }
      else             { F = C ^ (B | ~D);            g = (7 * i) & 15; }
      F = (F + A + K[i] + M[g]) >>> 0;
      A = D; D = C; C = B;
      B = (B + rol(F, S[i])) >>> 0;
    }
    a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0; c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
  }
  const out = new Uint8Array(16);
  const odv = new DataView(out.buffer);
  odv.setUint32(0, a0, true); odv.setUint32(4, b0, true); odv.setUint32(8, c0, true); odv.setUint32(12, d0, true);
  return out;
}
// ─── EVP_BytesToKey (MD5، بدون نمک، ۱ دور) — کلید از رشتهٔ پسورد ───
function ssEvpKey(passwordStr, klen) {
  const pw = new TextEncoder().encode(passwordStr);
  const d = new Uint8Array(((klen + 15) >> 4) << 4);
  let prev = new Uint8Array(0), off = 0;
  while (off < klen) {
    prev = md5(new Uint8Array([...prev, ...pw]));
    d.set(prev, off);
    off += 16;
  }
  return d.slice(0, klen);
}
async function ssHkdf(ikm, salt, len) {
  const k = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-1", salt, info: new TextEncoder().encode("ss-subkey") }, k, len * 8));
}
async function ssAesKey(subkey) {
  return crypto.subtle.importKey("raw", subkey, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}
const ssNonce = (c) => { const n = new Uint8Array(12); new DataView(n.buffer).setUint32(0, c, true); return n; };  // LE مثل go-shadowsocks2
function targetHeader(host, port) {
  let th;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    th = new Uint8Array(7);
    th[0] = 1;
    host.split(".").forEach((o, i) => { th[1 + i] = Number(o) & 255; });
  } else {
    const h = new TextEncoder().encode(host);
    th = new Uint8Array(2 + h.length + 2);
    th[0] = 3; th[1] = h.length; th.set(h, 2);
  }
  th[th.length - 2] = port >> 8; th[th.length - 1] = port & 255;
  return th;
}
async function ssOpen(tcp, srv, host, port) {
  const klen = parseInt(String(srv.kl || "32"), 10);
  const key = ssEvpKey(String(srv.k), klen);   // کلید از رشتهٔ پسورد (قرارداد AEAD کلاسیک)
  const enc = async (st, u8) => new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: ssNonce(st.n++), tagLength: 128 }, st.key, u8));
  const dec = async (st, u8) => new Uint8Array(await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: ssNonce(st.n++), tagLength: 128 }, st.key, u8));
  // مسیر ارسال: نمک تصادفی + زیرکلید
  const txSalt = crypto.getRandomValues(new Uint8Array(klen));
  const tx = { n: 0, key: await ssAesKey(await ssHkdf(key, txSalt, klen)) };
  const w = tcp.writable.getWriter();
  const th = targetHeader(host, port);
  const lh = new Uint8Array([th.length >> 8, th.length & 255]);
  const eL = await enc(tx, lh), eT = await enc(tx, th);
  const head = new Uint8Array(klen + eL.length + eT.length);
  head.set(txSalt, 0); head.set(eL, klen); head.set(eT, klen + eL.length);
  await w.write(head);
  // مسیر دریافت: نمک سرور (اولین klen بایت) + زیرکلید نو
  let rx = null, rxBuf = new Uint8Array(0), reader = tcp.readable.getReader();
  async function fill(n) {
    while (rxBuf.length < n) {
      const { done, value } = await reader.read();
      if (done || !value || !value.length) throw new Error("ss-eof");
      const nb = new Uint8Array(rxBuf.length + value.length);
      nb.set(rxBuf); nb.set(value, rxBuf.length);
      rxBuf = nb;
    }
  }
  async function take(n) { await fill(n); const out = rxBuf.slice(0, n); rxBuf = rxBuf.slice(n); return out; }
  return {
    async write(u8) {
      if (!u8 || !u8.length) return;
      for (let off = 0; off < u8.length; off += 0x3fff) {
        const part = u8.slice(off, Math.min(off + 0x3fff, u8.length));
        const h = new Uint8Array([part.length >> 8, part.length & 255]);
        const e1 = await enc(tx, h), e2 = await enc(tx, part);
        const out = new Uint8Array(e1.length + e2.length);
        out.set(e1); out.set(e2, e1.length);
        await w.write(out);
      }
    },
    async read() {
      if (!rx) {
        const salt = await take(klen);
        rx = { n: 0, key: await ssAesKey(await ssHkdf(key, salt, klen)) };
      }
      const h = await take(18);
      const hp = await dec(rx, h);
      const plen = (hp[0] << 8) | hp[1];
      const body = await take(plen + 16);
      return dec(rx, body);
    },
  };
}

const ACTIVE_CACHE = new Map();
async function activeName(env) {
  if (!env.DB) return null;
  const id = String(env.SRV_ID || "de");
  const c = ACTIVE_CACHE.get(id);
  if (c && Date.now() - c.ts < 60000) return c.name;
  try {
    const a = await env.DB.prepare("SELECT name FROM active_srv WHERE id = ?").bind(id).first();
    const name = (a && a.name) || null;
    ACTIVE_CACHE.set(id, { name, ts: Date.now() });
    return name;
  } catch { return c ? c.name : null; }
}

// ═══ کلاینت VLESS-TCP خام برای اعضای استخرِ vless ═══
function concat2(arrs) {
  const len = arrs.reduce((s, a) => s + a.length, 0);
  const out = new Uint8Array(len);
  let o = 0;
  for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
}
function vlessClientHeader(uuidDashed, host, port) {
  const hex = uuidDashed.replace(/-/g, "");
  const id = new Uint8Array(16);
  for (let i = 0; i < 16; i++) id[i] = parseInt(hex.substr(i * 2, 2), 16);
  let addr;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    const p = host.split(".");
    addr = new Uint8Array(5);
    addr[0] = 1;
    for (let i = 0; i < 4; i++) addr[i + 1] = +p[i];
  } else {
    const hb = new TextEncoder().encode(host);
    addr = new Uint8Array(2 + hb.length);
    addr[0] = 2; addr[1] = hb.length;
    addr.set(hb, 2);
  }
  const head = new Uint8Array(19);
  head[0] = 0;
  head.set(id, 1);
  head[17] = 0;
  head[18] = 1;
  return concat2([head, new Uint8Array([(port >> 8) & 255, port & 255]), addr]);
}
async function vlessOpen(tcp, member, host, port) {
  const w = tcp.writable.getWriter();
  const reader = tcp.readable.getReader();
  await w.write(vlessClientHeader(member.uuid, host, port));
  let buf = new Uint8Array(0);
  while (buf.length < 2) {
    const { done, value } = await reader.read();
    if (done || !value || !value.length) throw new Error("vless-member-closed");
    buf = concat2([buf, value]);
  }
  if (buf[0] !== 0 || buf[1] !== 0) throw new Error("vless-member-reject");
  let pending = buf.slice(2);
  return {
    async read() {
      if (pending && pending.length) { const o = pending; pending = null; return o; }
      const { done, value } = await reader.read();
      return (done || !value || !value.length) ? null : value;
    },
    write(d) { return w.write(d); },
  };
}

async function serveWs(server, uuid, env, earlyData) {
  server.accept();
  let tcp = null, writer = null, ssSession = null, upstreamReady = false, udpDnsMode = false;
  let closed = false, upB = 0, downB = 0, dest0 = "";
  const safeClose = () => {
    if (closed) return; closed = true;
    try { if (env.AE && (upB || downB)) env.AE.writeDataPoint({ blobs: [dest0.slice(0, 96)], doubles: [upB, downB] }); } catch {}
    try { tcp && tcp.close(); } catch {}
    try { server.close(); } catch {}
  };
  server.addEventListener("close", () => { try { tcp && tcp.close(); } catch {} });
  server.addEventListener("error", () => { try { tcp && tcp.close(); } catch {} });

    server.addEventListener("message", async ev => {
    if (closed) return;
    let data = new Uint8Array(ev.data);
    if (!upstreamReady) {
      upstreamReady = true;
      const vreq = parseVlessRequest(data);
      if (!vreq || vreq.uuid !== uuid) {
        server.send(new Uint8Array([0, 1]));
        safeClose(); return;
      }
      const payload = data.slice(vreq.payloadOffset);
      if (vreq.cmd === 2) {                       // UDP — فقط DNS (پورت ۵۳) با DoH داخلی
        server.send(vlessResponseHeader());
        if (vreq.port === 53) {
          udpDnsMode = true; dest0 = "udp:dns";
          upB += payload.length;
          await answerDns(server, payload, n => { downB += n; });
          // نشست باز می‌ماند؛ پرسش‌های بعدی در پیام‌های بعدی می‌آیند
          return;
        }
        server.send(new Uint8Array([0, 1]));      // UDP غیر DNS پشتیبانی نمی‌شود
        safeClose(); return;
      }
      if (vreq.cmd !== 1) { server.send(new Uint8Array([0, 1])); safeClose(); return; }
      const port = vreq.port, host = vreq.host;
      dest0 = host + ":" + port;
      upB += payload.length;
      try {
        // ═══ خروجی ثابت آلمان + سوییچ خودکار درون‌درخواستی (درجه ۳) ═══
        const pool = JSON.parse(String(env.SS_POOL || "[]"));
        if (!pool.length) throw new Error("pool-empty");
        let order = pool, curName = null;
        try {
          if (env.DB) {
            curName = await activeName(env);
            if (curName) order = [...pool].sort((x, y) => (x.n === curName ? -1 : (y.n === curName ? 1 : 0)));
          }
        } catch {}
        let opened = null;
        let lastErr = "";
        for (const srv of order) {
          try {
            const c = connect({ hostname: srv.h, port: parseInt(srv.p, 10) });
            const sess = (srv.proto === "vless") ? await vlessOpen(c, srv, host, port)
                                                 : await ssOpen(c, srv, host, port);
            await sess.write(payload);
            opened = { ss: sess, srv };
            break;
          } catch (e) { lastErr = String(e && e.message || e).slice(0, 100); continue; }
        }
        if (!opened) {
          try { server.send(new TextEncoder().encode("CONNFAIL:" + lastErr)); } catch {}
          throw new Error("all-servers-failed");
        }
        ssSession = opened.ss;
        if (env.DB && Math.random() < 0.1) {   // نمونه‌گیری ۱۰٪ → هر ثبت = ۱۰ اتصال
          env.DB.prepare(
            "INSERT INTO node_usage (worker, day, n) VALUES (?1, date('now'), 10) " +
            "ON CONFLICT(worker, day) DO UPDATE SET n = n + 10")
            .bind(String(env.WNAME || "unknown")).run().catch(() => {});
        }
        if (env.DB && opened.srv.n !== curName) {
          env.DB.prepare(
            "INSERT INTO active_srv (id, name, updated) VALUES (?2, ?1, datetime('now')) " +
            "ON CONFLICT(id) DO UPDATE SET name = ?1, updated = datetime('now')")
            .bind(opened.srv.n, String(env.SRV_ID || "de")).run().catch(() => {});
        }
        server.send(vlessResponseHeader());
        (async () => {
          try {
            for (;;) {
              const chunk = await opened.ss.read();
              if (!chunk || !chunk.length) break;
              downB += chunk.length;
              server.send(chunk);
            }
          } catch {}
          safeClose();
        })();
      } catch (e) { safeClose(); return; }
    } else if (udpDnsMode) {
      let buf = data;
      while (buf.length >= 2) {
        const need = (buf[0] << 8) | buf[1];
        if (buf.length < 2 + need) break;
        upB += need;
        answerDns(server, buf.slice(2, 2 + need), n => { downB += n; });
        buf = buf.slice(2 + need);
      }
    } else if (ssSession) {
      upB += data.length;
      try { await ssSession.write(data); } catch { safeClose(); }
    }
  });
  if (earlyData) {
    try { server.dispatchEvent(new MessageEvent("message", { data: earlyData })); } catch {}
  }
}

function concat(a, b) {
  const out = new Uint8Array(a.length + b.length);
  out.set(a); out.set(b, a.length);
  return out;
}

// قاب‌کردن دیتاگرام UDP برای کلاینت: [len ۲بایتی][داده]
function frameUdp(d) {
  const out = new Uint8Array(d.length + 2);
  out[0] = d.length >> 8; out[1] = d.length & 0xff;
  out.set(d, 2);
  return out;
}

// base64url بدون پدینگ برای DoH
function toBase64Url(u8) {
  let s = "";
  for (const b of u8) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// جواب DNS با DoH داخلی (بدون سوکت به کلادفلر)
async function answerDns(server, query, onBytes) {
  try {
    const b64 = toBase64Url(query);
    const r = await fetch("https://dns.google/dns-query?dns=" + b64,
      { headers: { accept: "application/dns-message" } });
    if (r.ok) {
      const ans = new Uint8Array(await r.arrayBuffer());
      if (onBytes) onBytes(ans.length);
      server.send(frameUdp(ans));
    }
  } catch {}
}
