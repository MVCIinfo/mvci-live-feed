const CONFIG_URL = "https://raw.githubusercontent.com/MVCIinfo/mvci-live-feed/main/config.json";
const DISPATCH_URL = "https://api.github.com/repos/MVCIinfo/mvci-live-feed/actions/workflows/deploy.yml/dispatches";
const HUB_URL = "https://pubsubhubbub.appspot.com/subscribe";
const FEED_URL = "https://www.youtube.com/xml/feeds/videos.xml?channel_id=";
const MAX_CONFIG = 64 * 1024;
const MAX_CALLBACK = 128 * 1024;
const COOLDOWN_MS = 120_000;
const RENEW_MARGIN = 30 * 60;
const LEASE_SECONDS = 864_000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" } });
}
function text(body, status = 200, contentType = "text/plain; charset=utf-8") {
  return new Response(status === 204 ? null : body, { status, headers: { "content-type": contentType, "cache-control": "no-store", "x-content-type-options": "nosniff" } });
}
function isHexSecret(s) { return typeof s === "string" && /^[a-fA-F0-9]{64}$/.test(s); }
function baseUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && u.hostname.endsWith(".workers.dev") && u.pathname === "/" && !u.search && !u.hash ? u.origin : null;
  } catch { return null; }
}
function configError(env) {
  if (!env.STATE || typeof env.STATE.get !== "function" || typeof env.STATE.put !== "function" || typeof env.STATE.list !== "function") return "STATE";
  if (typeof env.GITHUB_TOKEN !== "string" || !/^(github_pat_|ghp_)[A-Za-z0-9_]{20,}$/.test(env.GITHUB_TOKEN) || env.GITHUB_TOKEN.length > 512) return "GITHUB_TOKEN";
  if (!isHexSecret(env.HUB_SECRET)) return "HUB_SECRET";
  if (!isHexSecret(env.WEBHOOK_TOKEN)) return "WEBHOOK_TOKEN";
  if (!baseUrl(env.WORKER_URL)) return "WORKER_URL";
  return null;
}
async function readLimited(response, limit, timeoutMs = 10_000) {
  if ("ok" in response && !response.ok) throw new Error("upstream_status");
  const length = Number(response.headers.get("content-length"));
  if (Number.isFinite(length) && length > limit) throw new Error("too_large");
  if (!response.body) return "";
  const reader = response.body.getReader(); let bytes = 0; const parts = [];
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; reader.cancel().catch(() => {}); }, timeoutMs);
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      bytes += value.byteLength; if (bytes > limit) throw new Error("too_large"); parts.push(value);
    }
    if (timedOut) throw new Error("read_timeout");
  } finally { clearTimeout(timer); reader.releaseLock?.(); }
  const merged = new Uint8Array(bytes); let offset = 0; for (const p of parts) { merged.set(p, offset); offset += p.length; }
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(merged);
}
async function channels() {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const res = await fetch(CONFIG_URL, { signal: controller.signal, redirect: "error", headers: { accept: "application/json" } });
    const value = JSON.parse(await readLimited(res, MAX_CONFIG));
    if (!value || !Array.isArray(value.channels)) throw new Error("config_shape");
    const ids = [];
    for (const c of value.channels) if (c && c.enabled === true && typeof c.id === "string" && /^UC[A-Za-z0-9_-]{22}$/.test(c.id) && !ids.includes(c.id)) ids.push(c.id);
    if (ids.length > 40) throw new Error("too_many_channels");
    return ids;
  } finally { clearTimeout(timer); }
}
async function dispatch(env) {
  const res = await fetch(DISPATCH_URL, {
    method: "POST", redirect: "error",
    headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json", "content-type": "application/json", "user-agent": "mvci-live-feed-cloudflare-trigger" },
    body: JSON.stringify({ ref: "main" }), signal: AbortSignal.timeout(10_000)
  });
  if (res.status !== 204 && res.status !== 200) throw new Error(`dispatch_status_${res.status}`);
}
function safeLog(event, fields = {}) { console.log(JSON.stringify({ event, ...fields })); }
function xmlUnescape(s) {
  if (/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[\da-fA-F]+);)/.test(s)) throw new Error("xml_entity");
  return s.replace(/&(amp|lt|gt|quot|apos|#\d+|#x[\da-fA-F]+);/g, (_, n) => {
    const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" }[n]; if (named !== undefined) return named;
    const cp = n[1].toLowerCase() === "x" ? parseInt(n.slice(2), 16) : parseInt(n.slice(1), 10);
    if (!(cp === 9 || cp === 10 || cp === 13 || (cp >= 0x20 && cp <= 0xD7FF) || (cp >= 0xE000 && cp <= 0xFFFD) || (cp >= 0x10000 && cp <= 0x10FFFF))) throw new Error("xml_character");
    return String.fromCodePoint(cp);
  });
}
// Small namespace-aware XML reader: rejects DTDs/entities and checks balanced structure.
function parseEntries(xml) {
  xml = xml.replace(/^\uFEFF/, "");
  if (xml.length > MAX_CALLBACK || /<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error("xml_rejected");
  const tokens = xml.match(/<!\[CDATA\[[\s\S]*?\]\]>|<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<[^>]*>|[^<]+/g);
  if (!tokens || tokens.join("") !== xml) throw new Error("xml_malformed");
  const stack = []; const entries = []; let rootSeen = false;
  for (const token of tokens) {
    if (token.startsWith("<!--") || token.startsWith("<?")) continue;
    if (token.startsWith("<![CDATA[")) { if (!stack.length) throw new Error("xml_malformed"); stack.at(-1).text += token.slice(9, -3); continue; }
    if (!token.startsWith("<")) { if (stack.length) stack.at(-1).text += xmlUnescape(token); else if (token.trim()) throw new Error("xml_malformed"); continue; }
    if (token.startsWith("</")) {
      const m = token.match(/^<\/([\w.-]+:[\w.-]+|[\w.-]+)\s*>$/); if (!m || !stack.length || stack.at(-1).qname !== m[1]) throw new Error("xml_malformed");
      const node = stack.pop(); if (node.local === "entry" && node.ns === "http://www.w3.org/2005/Atom") entries.push(node); continue;
    }
    const m = token.match(/^<([\w.-]+:[\w.-]+|[\w.-]+)([\s\S]*?)\s*(\/?)>$/); if (!m) throw new Error("xml_malformed");
    const qname = m[1], attrsText = m[2], selfClose = !!m[3]; const attrs = {}; const attrRe = /([\w.-]+(?::[\w.-]+)?)\s*=\s*("[^"]*"|'[^']*')/g; let pos = 0, a;
    while ((a = attrRe.exec(attrsText))) { if (attrsText.slice(pos, a.index).trim()) throw new Error("xml_malformed"); attrs[a[1]] = xmlUnescape(a[2].slice(1, -1)); pos = attrRe.lastIndex; }
    if (attrsText.slice(pos).trim()) throw new Error("xml_malformed");
    const nsMap = Object.assign({}, stack.at(-1)?.nsMap || {}); for (const [k, v] of Object.entries(attrs)) { if (k === "xmlns") nsMap[""] = v; else if (k.startsWith("xmlns:")) nsMap[k.slice(6)] = v; }
    const parts = qname.split(":"), prefix = parts.length === 2 ? parts[0] : "", local = parts.at(-1), ns = nsMap[prefix] || "";
    const node = { qname, prefix, local, ns, nsMap, text: "", children: [] };
    if (stack.length) stack.at(-1).children.push(node);
    else if (rootSeen || local !== "feed" || ns !== "http://www.w3.org/2005/Atom") throw new Error("xml_malformed");
    else rootSeen = true;
    if (!selfClose) stack.push(node); else if (local === "entry" && ns === "http://www.w3.org/2005/Atom") entries.push(node);
  }
  if (stack.length || !rootSeen) throw new Error("xml_malformed");
  return entries.map(e => {
    const vids = [], cids = [];
    const walk = n => { for (const c of n.children) { if (c.local === "videoId" && c.ns === "http://www.youtube.com/xml/schemas/2015" && !c.children.length) vids.push(c.text.trim()); if (c.local === "channelId" && c.ns === "http://www.youtube.com/xml/schemas/2015" && !c.children.length) cids.push(c.text.trim()); walk(c); } };
    walk(e); return { videoIds: vids, channelIds: cids };
  });
}
async function signatureValid(request, env, body) {
  const value = request.headers.get("x-hub-signature"); if (!value) return false;
  const m = value.match(/^(sha1|sha256|sha384|sha512)=([a-fA-F0-9]+)$/); if (!m) return false;
  const hash = { sha1: "SHA-1", sha256: "SHA-256", sha384: "SHA-384", sha512: "SHA-512" }[m[1]];
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.HUB_SECRET), { name: "HMAC", hash }, false, ["verify"]);
  try { return await crypto.subtle.verify("HMAC", key, Uint8Array.from(m[2].match(/../g), x => parseInt(x, 16)), new TextEncoder().encode(body)); } catch { return false; }
}
async function handleCallback(request, env) {
  const body = await readLimited(request, MAX_CALLBACK);
  if (!(await signatureValid(request, env, body))) return text("invalid signature", 401);
  let entries; try { entries = parseEntries(body); } catch { return text("invalid XML", 400); }
  const allowed = new Set(await channels());
  const valid = entries.some(e => e.channelIds.some(c => allowed.has(c)) && e.videoIds.some(v => /^[A-Za-z0-9_-]{11}$/.test(v)));
  if (!valid) return text("no allowed notification", 202);
  const now = Date.now();
  try {
    const prev = Number(await env.STATE.get("lastNotificationDispatch"));
    if (Number.isFinite(prev) && now - prev < COOLDOWN_MS) return text("accepted", 204);
    await dispatch(env); await env.STATE.put("lastNotificationDispatch", String(now));
  } catch (e) { safeLog("notification_dispatch_failed", { reason: String(e.message).startsWith("dispatch_status_") ? e.message : "request_or_storage_error" }); return text("dispatch failed; retry later", 503); }
  return text("accepted", 204);
}
async function verifyRequest(request, env) {
  const u = new URL(request.url); const mode = u.searchParams.get("hub.mode"), topic = u.searchParams.get("hub.topic"), challenge = u.searchParams.get("hub.challenge"), lease = u.searchParams.get("hub.lease_seconds");
  if (!mode || !topic) return text("invalid verification", 400);
  const ids = await channels(); const id = ids.find(x => topic === FEED_URL + x);
  if (!id || !["subscribe", "unsubscribe"].includes(mode)) return text("topic not allowed", 403);
  if (!challenge || challenge.length > 512 || !/^[\x20-\x7e]+$/.test(challenge)) return text("invalid challenge", 400);
  if (mode === "subscribe") {
    const seconds = Number(lease); if (!Number.isSafeInteger(seconds) || seconds <= 0) return text("invalid lease", 400);
    try { await env.STATE.put(`lease:${id}`, JSON.stringify({ expiresAt: Date.now() + seconds * 1000, verifiedAt: Date.now() })); safeLog("subscription_verified", { channel: id }); }
    catch { safeLog("lease_storage_failed", { channel: id }); return text("storage unavailable", 503); }
    return text(challenge, 200, "application/octet-stream");
  }
  try { await env.STATE.delete(`lease:${id}`); } catch { safeLog("lease_storage_failed", { channel: id }); return text("storage unavailable", 503); }
  return text(challenge || "", 200, "application/octet-stream");
}
async function maintainSubscriptions(env) {
  const ids = await channels(), base = baseUrl(env.WORKER_URL); let errors = 0;
  for (const id of ids) {
    try {
      const leaseRaw = await env.STATE.get(`lease:${id}`); let lease = null; try { lease = leaseRaw && JSON.parse(leaseRaw); } catch {}
      const pendingRaw = await env.STATE.get(`pending:${id}`); const pending = Number(pendingRaw) || 0; const now = Date.now();
      if ((lease?.expiresAt && lease.expiresAt - now > RENEW_MARGIN * 1000) || (pending && now - pending < 30 * 60_000)) continue;
      const form = new URLSearchParams({ "hub.mode": "subscribe", "hub.callback": `${base}/youtube/${env.WEBHOOK_TOKEN}`, "hub.topic": FEED_URL + id, "hub.secret": env.HUB_SECRET, "hub.lease_seconds": String(LEASE_SECONDS), "hub.verify": "async" });
      const res = await fetch(HUB_URL, { method: "POST", redirect: "error", headers: { "content-type": "application/x-www-form-urlencoded" }, body: form.toString(), signal: AbortSignal.timeout(10_000) });
      if (!res.ok) throw new Error(`hub_status_${res.status}`);
      await env.STATE.put(`pending:${id}`, String(now)); safeLog("subscription_requested", { channel: id });
    } catch (e) { errors++; safeLog("subscription_request_failed", { channel: id, reason: String(e.message).startsWith("hub_status_") ? e.message : "request_or_storage_error" }); }
  }
  return errors;
}
async function runCron(env) {
  const missing = configError(env); if (missing) { safeLog("scheduled_run_not_configured", { missing }); return; }
  let failed = false;
  try { await dispatch(env); safeLog("scheduled_dispatch_ok", {}); }
  catch (e) { failed = true; safeLog("scheduled_dispatch_failed", { reason: String(e.message).startsWith("dispatch_status_") ? e.message : "request_failed" }); }
  try { const errors = await maintainSubscriptions(env); if (errors) failed = true; }
  catch { failed = true; safeLog("subscription_maintenance_failed", {}); }
  if (failed) safeLog("scheduled_run_incomplete", {});
}

export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    if (request.method === "GET" && u.pathname === "/health") return json({ ready: !configError(env), missing: configError(env) });
    const missing = configError(env); if (missing) return json({ error: "worker_not_configured", missing }, 503);
    if (request.method === "GET" && u.pathname === `/youtube/${env.WEBHOOK_TOKEN}`) {
      try { return await verifyRequest(request, env); } catch { return text("verification unavailable", 503); }
    }
    if (request.method === "POST" && u.pathname === `/youtube/${env.WEBHOOK_TOKEN}`) {
      try { return await handleCallback(request, env); }
  catch (e) { safeLog("notification_rejected_or_failed", { reason: e.message === "too_large" ? "too_large" : "processing_failed" }); return e.message === "too_large" ? text("too large", 413) : text("temporarily unavailable", 503); }
    }
    return text("not found", 404);
  },
  async scheduled(_event, env, ctx) { ctx.waitUntil(runCron(env)); }
};
