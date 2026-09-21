// 🦊 foxy-watch v3 — نگهبان تند-عکسل با Service Binding (بدون محدودیت 1042)
// هر ۵ دقیقه: uuidها از gist → هر نود با binding مستقیم چک می‌شود → مُرد؟
// → با محدودیت نرخ (D1) → dispatch فوری selfheal + ثبت در watch_log.
export default {
  async scheduled(ev, env, ctx) { ctx.waitUntil(safeCheck(env)); },
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.searchParams.get("key") !== String(env.KEY || "")) return new Response("not found", { status: 404 });
    try {
      const r = await safeCheck(env);
      return new Response(JSON.stringify(r), { headers: { "content-type": "application/json" } });
    } catch { return new Response(JSON.stringify({ err: "error" }), { status: 500, headers: { "content-type": "application/json" } }); }
  },
};
async function safeCheck(env) {
  try { return await check(env); } catch { return { at: new Date().toISOString(), err: "error" }; }
}
async function check(env) {
  const bust = Math.floor(Date.now() / 60000);
  const gist = await (await fetch(String(env.GIST_RAW) + "?v=" + bust, { headers: { "user-agent": "Mozilla/5.0" } })).text();
  const wanted = String(env.NODE_IDS || "de,us,gb").split(",").map(s => s.trim()).filter(Boolean);
  const uuids = {};
  for (const l of gist.split("\n")) {
    if (!l.startsWith("vless://")) continue;
    let label = "";
    try { label = decodeURIComponent(l.split("#")[1] || ""); } catch {}
    const cc = MAP[label.slice(0, 4)];
    if (cc && wanted.includes(cc) && !uuids[cc]) uuids[cc] = l.slice(8).split("@")[0];
  }
  const dead = [], status = {}, checked = [];
  for (const id of wanted) {
    const svc = env["S_" + id.toUpperCase()];
    if (!svc || !uuids[id]) continue;
    checked.push(id);
    let s = await svcStatus(svc, uuids[id]);
    if (s !== 200) { await new Promise(r => setTimeout(r, 3000)); s = await svcStatus(svc, uuids[id]); }
    status[id] = s;
    if (s !== 200) dead.push(id);
  }
  // ═══ سلامت تانل (tcheck): فقط گزارش — dispatch فقط برای مرگ پروسه ═══
  const tunnel = {};
  // گرهٔ اختصاصی آلمان-۲: بایندینگ سرویس رله (fetch بیرونیِ هم‌اکانت = 404)
  if (env.S_DE2) {
    try {
      const r = await env.S_DE2.fetch("https://svc/health");
      tunnel.de2 = { ok: r.status === 200, member: "relay+render", detail: ["HTTP " + r.status] };
    } catch { tunnel.de2 = { ok: false, member: "relay+render", detail: ["err"] }; }
  }
  for (const id of checked) {
    const svc = env["S_" + id.toUpperCase()];
    if (!svc || !uuids[id]) continue;
    try {
      const r = await svc.fetch("https://svc/tcheck?key=" + uuids[id]);
      const j = await r.json();
      tunnel[id] = { ok: !!j.ok, member: j.member || "", detail: (j.detail || []).slice(0, 2) };
    } catch { tunnel[id] = { ok: false, member: "", detail: ["err"] }; }
  }
  let dispatched = null;
  if (dead.length) dispatched = await dispatchRateLimited(env, dead);
  const report = { at: new Date().toISOString(), checked, status, tunnel, dead, dispatched };
  await logReport(env, report);
  return report;
}
const MAP = { "\u{1F1E9}\u{1F1EA}": "de", "\u{1F1FA}\u{1F1F8}": "us", "\u{1F1EC}\u{1F1E7}": "gb",
"\u{1F1F3}\u{1F1F1}": "nl", "\u{1F1EB}\u{1F1F7}": "fr", "\u{1F1E8}\u{1F1E6}": "ca",
"\u{1F1F8}\u{1F1EC}": "sg", "\u{1F1EF}\u{1F1F5}": "jp", "\u{1F1E8}\u{1F1ED}": "ch",
"\u{1F1F8}\u{1F1EA}": "se", "\u{1F1E6}\u{1F1F9}": "at", "\u{1F1F9}\u{1F1F7}": "tr",
"\u{1F1E6}\u{1F1EA}": "ae", "\u{1F1F7}\u{1F1FA}": "ru", "\u{1F1F5}\u{1F1F1}": "pl",
"\u{1F1EE}\u{1F1F9}": "it" };
async function svcStatus(svc, uuid) {
  try {
    const r = await svc.fetch("https://svc/usage?key=" + uuid);
    return r.status;
  } catch { return "ERR"; }
}
async function dispatchRateLimited(env, dead) {
  try {
    // درجه BBN: فقط مرگ دو-دور-پیاپی (ضد هشدار پنجرهٔ پخش)
    const last = await env.DB.prepare("SELECT dead FROM watch_log ORDER BY at DESC LIMIT 1").first();
    if (last && last.dead) {
      let prev = []; try { prev = JSON.parse(last.dead); } catch {}
      if (!dead.some(d => prev.includes(d))) return "streak-wait";
    }
    const row = await env.DB.prepare("SELECT at FROM watch_log WHERE dispatched = 'ok' ORDER BY at DESC LIMIT 1").first();
    if (row) {
      const last = Date.parse(row.at);
      if (Date.now() - last < 10 * 60 * 1000) return "rate-limited";
    }
    const dr = await fetch("https://api.github.com/repos/Wboyx/foxy-roulette/actions/workflows/selfheal.yml/dispatches", {
      method: "POST",
      headers: { "Authorization": "token " + env.GH, "content-type": "application/json", "User-Agent": "foxy-watch" },
      body: JSON.stringify({ ref: "main" }),
    });
    return dr.status === 204 ? "ok" : dr.status;
  } catch { return "err"; }
}
async function logReport(env, report) {
  try {
    await env.DB.prepare("INSERT INTO watch_log (at, status, dead, dispatched) VALUES (?1, ?2, ?3, ?4)")
      .bind(report.at, JSON.stringify(report.status || {}), JSON.stringify(report.dead || []), String(report.dispatched ?? ""))
      .run();
    await env.DB.prepare("DELETE FROM watch_log WHERE at < datetime('now', '-3 days')").run();
  } catch {}
}
