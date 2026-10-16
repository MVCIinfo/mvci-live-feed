const CONFIG_URL = "https://raw.githubusercontent.com/MVCIinfo/mvci-live-feed/main/config.json";
const DISPATCH_URL = "https://api.github.com/repos/MVCIinfo/mvci-live-feed/actions/workflows/deploy.yml/dispatches";
const HUB_URL = "https://pubsubhubbub.appspot.com/subscribe";
const FEED_URL = "https://www.youtube.com/xml/feeds/videos.xml?channel_id=";
const MAX_CONFIG = 64 * 1024;
const MAX_CALLBACK = 128 * 1024;
const MAX_RSS = 256 * 1024;
const MAX_API_RESPONSE = 512 * 1024;
const SNAPSHOT_KEY = "monitor:snapshot";
const MAX_TRACKED = 120;
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
  if (typeof env.YOUTUBE_API_KEY !== "string" || env.YOUTUBE_API_KEY.length < 20 || env.YOUTUBE_API_KEY.length > 256 || /[\s&]/.test(env.YOUTUBE_API_KEY)) return "YOUTUBE_API_KEY";
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
function parseEntries(xml, maxSize = MAX_CALLBACK) {
  xml = xml.replace(/^\uFEFF/, "");
  if (xml.length > maxSize || /<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error("xml_rejected");
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
    const vids = [], cids = []; let title = "", published = "";
    const walk = n => { for (const c of n.children) { if (c.local === "videoId" && c.ns === "http://www.youtube.com/xml/schemas/2015" && !c.children.length) vids.push(c.text.trim()); if (c.local === "channelId" && c.ns === "http://www.youtube.com/xml/schemas/2015" && !c.children.length) cids.push(c.text.trim()); if (c.local === "title" && c.ns === "http://www.w3.org/2005/Atom" && !c.children.length) title = c.text.trim(); if (c.local === "published" && c.ns === "http://www.w3.org/2005/Atom" && !c.children.length) published = c.text.trim(); walk(c); } };
    walk(e); return { videoIds: vids, channelIds: cids, title, published };
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
async function maintainSubscriptions(env, ids) {
  const base = baseUrl(env.WORKER_URL); let errors = 0, attempts = 0;
  for (const id of ids) {
    if (attempts >= 4) break;
    try {
      const leaseRaw = await env.STATE.get(`lease:${id}`); let lease = null; try { lease = leaseRaw && JSON.parse(leaseRaw); } catch {}
      const pendingRaw = await env.STATE.get(`pending:${id}`); const pending = Number(pendingRaw) || 0; const now = Date.now();
      if ((lease?.expiresAt && lease.expiresAt - now > RENEW_MARGIN * 1000) || (pending && now - pending < 30 * 60_000)) continue;
      attempts++;
      const form = new URLSearchParams({ "hub.mode": "subscribe", "hub.callback": `${base}/youtube/${env.WEBHOOK_TOKEN}`, "hub.topic": FEED_URL + id, "hub.secret": env.HUB_SECRET, "hub.lease_seconds": String(LEASE_SECONDS), "hub.verify": "async" });
      const res = await fetch(HUB_URL, { method: "POST", redirect: "error", headers: { "content-type": "application/x-www-form-urlencoded" }, body: form.toString(), signal: AbortSignal.timeout(10_000) });
      if (!res.ok) throw new Error(`hub_status_${res.status}`);
      await env.STATE.put(`pending:${id}`, String(now)); safeLog("subscription_requested", { channel: id });
    } catch (e) { errors++; safeLog("subscription_request_failed", { reason: String(e.message).startsWith("hub_status_") ? e.message : "request_or_storage_error" }); }
  }
  return errors;
}
function normalize(s) { return String(s || "").normalize("NFKC").toLowerCase(); }
function normalizeExcluded(s) { return normalize(s).replace(/\s+/gu, ""); }
function eligibleTitle(title, cfg) {
  const includes = (Array.isArray(cfg.keywords) ? cfg.keywords : [cfg.keyword || "MVCI"]).filter(x => typeof x === "string" && x.length).map(normalize);
  const excludes = (Array.isArray(cfg.exclude_keywords) ? cfg.exclude_keywords : ["MVCI 闘魂部"]).filter(x => typeof x === "string" && x.trim()).map(normalizeExcluded);
  const t = normalize(title);
  if (!includes.some(k => t.includes(k))) return false;
  const compact = normalizeExcluded(title);
  return !excludes.some(k => compact.includes(k));
}
async function rssFor(id) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const res = await fetch(FEED_URL + id, { redirect: "error", headers: { accept: "application/atom+xml, application/xml" }, signal: controller.signal });
    const entries = parseEntries(await readLimited(res, MAX_RSS), MAX_RSS);
    return entries.filter(e => e.channelIds.includes(id) && e.videoIds.length && /^[A-Za-z0-9_-]{11}$/.test(e.videoIds[0]) && e.title && Number.isFinite(Date.parse(e.published)))
      .map(e => ({ id: e.videoIds[0], channelId: id, title: e.title, published: e.published, publishedAt: Date.parse(e.published) }));
  } finally { clearTimeout(timer); }
}
async function mapLimit(items, limit, fn) {
  const out = new Array(items.length); let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => { for (;;) { const i = next++; if (i >= items.length) return; out[i] = await fn(items[i]); } }));
  return out;
}
async function videoDetails(env, ids) {
  const map = new Map();
  for (let i = 0; i < ids.length; i += 50) {
    const batch = ids.slice(i, i + 50);
    const url = "https://www.googleapis.com/youtube/v3/videos?part=snippet,liveStreamingDetails,status&id=" + batch.join(",");
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10_000);
    try {
      const res = await fetch(url, { redirect: "error", headers: { "x-goog-api-key": env.YOUTUBE_API_KEY, accept: "application/json" }, signal: controller.signal });
      const data = JSON.parse(await readLimited(res, MAX_API_RESPONSE));
      if (!Array.isArray(data.items)) throw new Error("youtube_api_shape");
      for (const item of data.items) {
        if (!item || !batch.includes(item.id)) continue;
        const live = item.liveStreamingDetails || {}, broadcast = item.snippet?.liveBroadcastContent;
        const lifecycle = live.actualStartTime ? (live.actualEndTime ? "ended" : "live") : broadcast === "live" ? "live" : broadcast === "upcoming" ? "upcoming" : "normal";
        map.set(item.id, { lifecycle, title: String(item.snippet?.title || "") });
      }
      for (const id of batch) if (!map.has(id)) map.set(id, { lifecycle: "unavailable" });
    } finally { clearTimeout(timer); }
  }
  return map;
}
async function monitor(env, ids, cfg) {
  const oldRaw = await env.STATE.get(SNAPSHOT_KEY); let previous = null;
  if (oldRaw) { try { previous = JSON.parse(oldRaw); if (!previous || !Array.isArray(previous.candidates)) previous = null; } catch { previous = null; } }
  const priorCandidates = previous?.candidates || [];
  const allowed = new Set(ids);
  const feeds = await mapLimit(ids, 4, async id => {
    try { return { id, ok: true, entries: await rssFor(id) }; }
    catch { return { id, ok: false, entries: [] }; }
  });
  const feedStatus = new Map(feeds.map(x => [x.id, x.ok]));
  const failedCount = feeds.filter(x => !x.ok).length;
  const latest = new Map();
  for (const result of feeds) if (result.ok) for (const e of result.entries) if (eligibleTitle(e.title, cfg)) {
    const cur = latest.get(e.channelId); if (!cur || e.publishedAt > cur.publishedAt) latest.set(e.channelId, e);
  }
  const candidates = new Map();
  for (const item of latest.values()) candidates.set(item.id, { ...item, current: true });
  // On failed channels, retain every known candidate so the API can still report lifecycle changes.
  // On successful channels, retain only prior live/upcoming streams to catch their end transition.
  for (const item of priorCandidates) {
    if (!allowed.has(item.channelId)) continue;
    const failed = feedStatus.get(item.channelId) === false;
    const carry = failed || item.lifecycle === "live" || item.lifecycle === "upcoming";
    if (!carry || !eligibleTitle(item.title, cfg) || candidates.has(item.id)) continue;
    candidates.set(item.id, { ...item, current: failed ? !!item.current : false });
  }
  if (ids.length > 0 && failedCount === ids.length && candidates.size === 0) throw new Error("all_feeds_failed_without_candidates");
  const selected = [...candidates.values()].sort((a, b) => (b.publishedAt || Date.parse(b.published || "") || 0) - (a.publishedAt || Date.parse(a.published || "") || 0)).slice(0, MAX_TRACKED);
  const details = await videoDetails(env, selected.map(x => x.id));
  const apiFilteredIds = new Set();
  const next = [];
  for (const x of selected) {
    const detail = details.get(x.id) || { lifecycle: "unavailable" };
    const title = detail.title || x.title;
    // API titles are authoritative when returned; current configuration exclusions always win.
    if (!eligibleTitle(title, cfg)) { if (detail.title) apiFilteredIds.add(x.id); continue; }
    next.push({ id: x.id, channelId: x.channelId, title, published: x.published || new Date(x.publishedAt || 0).toISOString(), publishedAt: x.publishedAt || Date.parse(x.published || "") || 0, lifecycle: detail.lifecycle, current: !!x.current });
  }
  next.sort((a,b) => a.id.localeCompare(b.id));
  const priorById = new Map(priorCandidates.map(x => [x.id, x]));
  const nextById = new Map(next.map(x => [x.id, x]));
  const changed = !previous || next.some(x => {
    const old = priorById.get(x.id);
    return !old || old.title !== x.title || old.lifecycle !== x.lifecycle || old.current !== x.current;
  }) || priorCandidates.some(old => {
    if (nextById.has(old.id)) return false;
    if (apiFilteredIds.has(old.id)) return true;
    if (!allowed.has(old.channelId)) return true;
    if (!eligibleTitle(old.title, cfg)) return true;
    if (feedStatus.get(old.channelId) === false) return false;
    // Ended carry records naturally age out after their transition was committed.
    if (!old.current && old.lifecycle === "ended") return false;
    return true;
  });
  return { previous, snapshot: { checkedAt: new Date().toISOString(), candidates: next }, changed, partial: failedCount > 0 };
}

async function runCron(env) {
  const missing = configError(env); if (missing) { safeLog("scheduled_run_not_configured", { missing }); return; }
  let status = "ok", tracked = 0, ids = [];
  try {
    const res = await fetch(CONFIG_URL, { redirect: "error", headers: { accept: "application/json" }, signal: AbortSignal.timeout(10_000) });
    const cfg = JSON.parse(await readLimited(res, MAX_CONFIG));
    if (!cfg || !Array.isArray(cfg.channels)) throw new Error("config_shape");
    ids = []; for (const c of cfg.channels) if (c?.enabled === true && typeof c.id === "string" && /^UC[A-Za-z0-9_-]{22}$/.test(c.id) && !ids.includes(c.id)) ids.push(c.id);
    if (ids.length > 40) throw new Error("too_many_channels");
    let subErrors = 0; try { subErrors = await maintainSubscriptions(env, ids); if (subErrors) status = "partial"; } catch { status = "partial"; safeLog("subscription_maintenance_failed", {}); }
    const result = await monitor(env, ids, cfg); tracked = result.snapshot.candidates.length;
    if (result.partial && status === "ok") status = "partial";
    if (result.changed) {
      try {
        await dispatch(env);
        safeLog("monitor_dispatch_ok", { reason: result.previous ? "change" : "baseline" });
      } catch (e) { status = "dispatch_failed"; safeLog("monitor_dispatch_failed", { reason: String(e.message).startsWith("dispatch_status_") ? e.message : "request_failed" }); }
      if (status !== "dispatch_failed") await env.STATE.put(SNAPSHOT_KEY, JSON.stringify(result.snapshot));
    } else await env.STATE.put(SNAPSHOT_KEY, JSON.stringify(result.snapshot));
  } catch (e) {
    status = "monitor_failed";
    const reason = ["too_large", "upstream_status", "read_timeout", "config_shape", "too_many_channels", "all_feeds_failed_without_candidates", "xml_rejected", "xml_malformed", "xml_entity", "xml_character"].includes(e.message) ? e.message : "upstream_or_storage_error";
    safeLog("monitor_failed", { reason });
  }
  try { await env.STATE.put("monitor:health", JSON.stringify({ at: new Date().toISOString(), status, tracked })); } catch { safeLog("health_storage_failed", {}); }
  safeLog("scheduled_run_complete", { status, tracked });
}


export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    if (request.method === "GET" && u.pathname === "/health") {
      const missing = configError(env); let monitorState = null;
      if (!missing) { try { const raw = await env.STATE.get("monitor:health"); monitorState = raw ? JSON.parse(raw) : null; } catch {} }
      return json({ ready: !missing, missing, monitor: monitorState && { at: monitorState.at, status: monitorState.status, tracked: monitorState.tracked } });
    }
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
