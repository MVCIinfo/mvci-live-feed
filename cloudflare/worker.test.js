import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker from "./worker.js";

globalThis.crypto ||= webcrypto;
const A = "UC" + "a".repeat(22), B = "UC" + "b".repeat(22), VIDEO = "abcdefghijk";
const secret = "1a".repeat(32), ghToken = "github_pat_" + "x".repeat(40);
const config = { channels: [{ id: A, enabled: true }, { id: A, enabled: true }, { id: B, enabled: false }, { id: "UCbad", enabled: true }] };
function makeEnv({ configValue = config, githubStatus = 204, hubStatus = 202, state = new Map() } = {}) {
  const kv = {
    async get(k) { return state.has(k) ? state.get(k) : null; },
    async put(k, v) { state.set(k, String(v)); },
    async delete(k) { state.delete(k); },
    async list({ prefix = "" } = {}) { return { keys: [...state.keys()].filter(k => k.startsWith(prefix)).map(name => ({ name })) }; }
  };
  const env = { STATE: kv, YOUTUBE_API_KEY: "test-public-read-api-key-0123456789", WORKER_URL: "https://mvci-feed-trigger.workers.dev", GITHUB_TOKEN: ghToken, HUB_SECRET: secret, WEBHOOK_TOKEN: secret, state };
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("raw.githubusercontent.com")) return new Response(JSON.stringify(configValue), { status: 200 });
    if (String(url).includes("api.github.com")) return new Response(null, { status: githubStatus });
    if (String(url).includes("pubsubhubbub")) return new Response(hubStatus === 204 ? null : "", { status: hubStatus });
    throw new Error("unexpected fetch destination");
  };
  return { env, calls, state };
}
const feed = (channel = A, video = VIDEO, prefix = "yt") => `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:${prefix}="http://www.youtube.com/xml/schemas/2015"><entry><${prefix}:videoId>${video}</${prefix}:videoId><${prefix}:channelId>${channel}</${prefix}:channelId></entry></feed>`;
async function signedPost(env, xml, algorithm = "sha256") {
  const hash = { sha1: "SHA-1", sha256: "SHA-256", sha384: "SHA-384", sha512: "SHA-512" }[algorithm];
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.HUB_SECRET), { name: "HMAC", hash }, false, ["sign"]);
  const sig = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(xml))).toString("hex");
  return worker.fetch(new Request(`https://mvci-feed-trigger.workers.dev/youtube/${env.WEBHOOK_TOKEN}`, { method: "POST", headers: { "x-hub-signature": `${algorithm}=${sig}` }, body: xml }), env);
}

test("notification accepts a namespace prefix variant, dispatches once, and accepts GitHub 204/200", async () => {
  for (const status of [204, 200]) {
    const { env, calls, state } = makeEnv({ githubStatus: status });
    const res = await signedPost(env, feed(A, VIDEO, "media"));
    assert.equal(res.status, 204);
    assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 1);
    assert.deepEqual(JSON.parse(calls.find(c => c.url.includes("api.github.com")).init.body), { ref: "main" });
    assert.ok(state.has("lastNotificationDispatch"));
  }
});

test("notification parser supports numeric XML entities and inert CDATA", async () => {
  const { env, calls } = makeEnv();
  const xml = `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId><![CDATA[${VIDEO}]]></yt:videoId><yt:channelId>UC&#97;aaaaaaaaaaaaaaaaaaaaa</yt:channelId></entry></feed>`;
  assert.equal((await signedPost(env, xml)).status, 204);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 1);
});

test("signature verification preserves a UTF-8 BOM in the signed body", async () => {
  const { env, calls } = makeEnv();
  assert.equal((await signedPost(env, "\uFEFF" + feed())).status, 204);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 1);
});

test("invalid or unsigned signatures never reach GitHub", async () => {
  const { env, calls } = makeEnv(); const url = `https://x/youtube/${env.WEBHOOK_TOKEN}`;
  assert.equal((await worker.fetch(new Request(url, { method: "POST", body: feed() }), env)).status, 401);
  assert.equal((await worker.fetch(new Request(url, { method: "POST", headers: { "x-hub-signature": "sha256=" + "00".repeat(32) }, body: feed() }), env)).status, 401);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 0);
});

test("invalid XML, DTD, invalid ids, wrong namespace, and oversized bodies do not dispatch", async () => {
  const { env, calls } = makeEnv();
  for (const body of ["<!DOCTYPE x [<!ENTITY a 'z'>]><feed/>", "<feed><entry>", feed(A, "short"), feed(A, VIDEO).replace("http://www.youtube.com/xml/schemas/2015", "urn:wrong"), feed().replace("<feed", "<notfeed").replace("</feed>", "</notfeed>")]) {
    assert.notEqual((await signedPost(env, body)).status, 204);
  }
  const large = "x".repeat(128 * 1024 + 1);
  const oversized = await worker.fetch(new Request(`https://x/youtube/${env.WEBHOOK_TOKEN}`, { method: "POST", headers: { "x-hub-signature": "sha256=" + "00".repeat(32) }, body: large }), env);
  assert.equal(oversized.status, 413);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 0);
});

test("channel list deduplicates valid IDs and rejects more than forty", async () => {
  const { env, calls } = makeEnv();
  const good = await signedPost(env, feed()); assert.equal(good.status, 204);
  const many = Array.from({ length: 41 }, (_, i) => ({ enabled: true, id: "UC" + i.toString(36).padStart(22, "0") }));
  const overflow = makeEnv({ configValue: { channels: many } });
  assert.equal((await signedPost(overflow.env, feed())).status, 503);
  assert.equal(overflow.calls.filter(c => c.url.includes("api.github.com")).length, 0);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 1);
});

test("valid subscription challenge is returned only for the current exact configured topic", async () => {
  const { env, state } = makeEnv(); const base = `https://x/youtube/${env.WEBHOOK_TOKEN}`;
  const good = new URLSearchParams({ "hub.mode": "subscribe", "hub.topic": `https://www.youtube.com/xml/feeds/videos.xml?channel_id=${A}`, "hub.challenge": "challenge-123", "hub.lease_seconds": "3600" });
  const res = await worker.fetch(new Request(`${base}?${good}`), env);
  assert.equal(res.status, 200); assert.equal(res.headers.get("content-type"), "application/octet-stream"); assert.equal(await res.text(), "challenge-123");
  assert.ok(state.has(`lease:${A}`));
  good.set("hub.topic", `https://www.youtube.com/xml/feeds/videos.xml?channel_id=${B}`);
  assert.equal((await worker.fetch(new Request(`${base}?${good}`), env)).status, 403);
  good.set("hub.topic", `https://www.youtube.com/xml/feeds/videos.xml?channel_id=${A}`); good.set("hub.challenge", "\n");
  assert.equal((await worker.fetch(new Request(`${base}?${good}`), env)).status, 400);
  good.set("hub.mode", "unsubscribe"); good.set("hub.challenge", "");
  assert.equal((await worker.fetch(new Request(`${base}?${good}`), env)).status, 400);
});

test("a successful notification cooldown suppresses duplicates; a failed dispatch is retryable", async () => {
  let bundle = makeEnv();
  assert.equal((await signedPost(bundle.env, feed())).status, 204);
  assert.equal((await signedPost(bundle.env, feed())).status, 204);
  assert.equal(bundle.calls.filter(c => c.url.includes("api.github.com")).length, 1);
  bundle = makeEnv({ githubStatus: 500 });
  assert.equal((await signedPost(bundle.env, feed())).status, 503);
  assert.equal(bundle.state.has("lastNotificationDispatch"), false);
});

function monitorFeed(channel = A, video = VIDEO, title = "MVCI stream", published = "2026-10-17T10:00:00Z") {
  return `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>${video}</yt:videoId><yt:channelId>${channel}</yt:channelId><title>${title}</title><published>${published}</published></entry></feed>`;
}
function configureCron(bundle, { lifecycle = "normal", title = "MVCI stream", apiStatus = 200, dispatchStatus = 204, rssFailure = false } = {}) {
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    bundle.calls.push({ url: String(url), init });
    const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify(config), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return rssFailure ? new Response("", { status: 503 }) : new Response(monitorFeed(A, VIDEO, title), { status: 200 });
    if (u.includes("googleapis.com/youtube/v3/videos")) return new Response(JSON.stringify({ items: [{ id: VIDEO, snippet: { title, liveBroadcastContent: lifecycle === "live" ? "live" : lifecycle === "upcoming" ? "upcoming" : "none" }, liveStreamingDetails: lifecycle === "live" ? { actualStartTime: "2026-10-17T10:01:00Z" } : lifecycle === "ended" ? { actualStartTime: "2026-10-17T10:01:00Z", actualEndTime: "2026-10-17T10:30:00Z" } : {} }] }), { status: apiStatus });
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    if (u.includes("api.github.com")) return new Response(null, { status: dispatchStatus });
    throw new Error("unexpected fetch destination");
  };
  return () => { globalThis.fetch = baseFetch; };
}
async function runScheduled(env) { let job; await worker.scheduled({}, env, { waitUntil(p) { job = p; } }); await job; }

test("cron seeds baseline, then dispatches only changed snapshots", async () => {
  const b = makeEnv(); const restore = configureCron(b);
  try {
    await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
    b.calls.length = 0; await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 0);
    assert.equal(JSON.parse(b.state.get("monitor:health")).status, "ok");
  } finally { restore(); }
});

test("cron detects upcoming to live to ended and carries an older live candidate", async () => {
  const b = makeEnv(); let lifecycle = "upcoming";
  const restore = configureCron(b, { lifecycle });
  try {
    await runScheduled(b.env); // initial baseline
    globalThis.fetch = async (url, init = {}) => {
      b.calls.push({ url: String(url), init }); const u = String(url);
      if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify(config), { status: 200 });
      if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return new Response(monitorFeed(A, "zzzzzzzzzzz", "MVCI newer", "2026-10-17T11:00:00Z"), { status: 200 });
      if (u.includes("googleapis.com/youtube/v3/videos")) {
        const ids = new URL(u).searchParams.get("id").split(",");
        const items = ids.map(id => id === VIDEO ? { id, snippet: { title: "MVCI stream", liveBroadcastContent: lifecycle }, liveStreamingDetails: lifecycle === "live" ? { actualStartTime: "2026-10-17T10:01:00Z" } : lifecycle === "ended" ? { actualStartTime: "2026-10-17T10:01:00Z", actualEndTime: "2026-10-17T10:30:00Z" } : {} } : { id, snippet: { title: "MVCI newer", liveBroadcastContent: "none" }, liveStreamingDetails: {} });
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
      if (u.includes("api.github.com")) return new Response(null, { status: 204 });
      throw new Error("unexpected fetch destination");
    };
    b.calls.length = 0; lifecycle = "live"; await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
    b.calls.length = 0; lifecycle = "ended"; await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
    assert.ok(JSON.parse(b.state.get("monitor:snapshot")).candidates.some(x => x.id === VIDEO && x.lifecycle === "ended"));
    b.calls.length = 0; await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 0, "dropping an ended carry candidate is not a new change");
  } finally { restore(); }
});

test("exclude keywords win; API and RSS failures preserve committed state; dispatch failure retries", async () => {
  const b = makeEnv(); const restore = configureCron(b, { title: "MVCI闘魂部" });
  try {
    await runScheduled(b.env);
    assert.equal(b.calls.filter(c => c.url.includes("googleapis.com/youtube/v3/videos")).length, 0);
  } finally { restore(); }
  const c = makeEnv(); const restore2 = configureCron(c);
  try {
    await runScheduled(c.env); const committed = c.state.get("monitor:snapshot");
    configureCron(c, { rssFailure: true }); c.calls.length = 0; await runScheduled(c.env);
    assert.equal(c.state.get("monitor:snapshot"), committed);
    assert.equal(c.calls.filter(x => x.url.includes("api.github.com")).length, 0);
    configureCron(c, { apiStatus: 503 }); c.calls.length = 0; await runScheduled(c.env);
    assert.equal(c.state.get("monitor:snapshot"), committed);
    assert.equal(c.calls.filter(x => x.url.includes("api.github.com")).length, 0);
  } finally { restore2(); }
  const d = makeEnv(); const restore3 = configureCron(d, { dispatchStatus: 500 });
  try {
    await runScheduled(d.env); assert.equal(d.state.has("monitor:snapshot"), false);
    configureCron(d, { dispatchStatus: 204 }); await runScheduled(d.env);
    assert.equal(d.state.has("monitor:snapshot"), true);
  } finally { restore3(); }
});

test("cron stays within subrequest bound and never exposes API key", async () => {
  const b = makeEnv(); const restore = configureCron(b);
  const originalLog = console.log, logs = []; console.log = x => logs.push(String(x));
  try {
    await runScheduled(b.env);
    assert.ok(b.calls.length <= 49, `observed ${b.calls.length}`);
    const api = b.calls.find(c => c.url.includes("googleapis.com"));
    assert.equal(new URL(api.url).searchParams.has("key"), false);
    assert.equal(api.init.headers["x-goog-api-key"], b.env.YOUTUBE_API_KEY);
    assert.ok(!logs.join("\n").includes(b.env.YOUTUBE_API_KEY));
  } finally { console.log = originalLog; restore(); }
});


test("40 channels plus 80 carried live candidates stay within 49 external requests", async () => {
  const ids = Array.from({ length: 40 }, (_, i) => "UC" + String(i).padStart(22, "a"));
  const oldIds = Array.from({ length: 80 }, (_, i) => "old" + String(i).padStart(8, "0"));
  const state = new Map([["monitor:snapshot", JSON.stringify({ candidates: oldIds.map((id, i) => ({ id, channelId: ids[i % 40], title: "MVCI old", lifecycle: "live" })) })]]);
  const b = makeEnv({ configValue: { channels: ids.map(id => ({ id, enabled: true })) }, state });
  globalThis.fetch = async (url, init = {}) => {
    b.calls.push({ url: String(url), init }); const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify({ channels: ids.map(id => ({ id, enabled: true })) }), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) {
      const id = new URL(u).searchParams.get("channel_id"), n = ids.indexOf(id);
      return new Response(monitorFeed(id, "new" + String(n).padStart(8, "0"), "MVCI fresh", `2026-10-17T${String(n % 24).padStart(2,"0")}:00:00Z`), { status: 200 });
    }
    if (u.includes("googleapis.com/youtube/v3/videos")) {
      const requested = new URL(u).searchParams.get("id").split(",");
      return new Response(JSON.stringify({ items: requested.map(id => ({ id, snippet: { title: "MVCI stream", liveBroadcastContent: "none" }, liveStreamingDetails: { actualStartTime: "2026-10-17T10:00:00Z" } })) }), { status: 200 });
    }
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    throw new Error("unexpected fetch destination");
  };
  await runScheduled(b.env);
  assert.equal(b.calls.filter(c => c.url.includes("pubsubhubbub")).length, 4);
  assert.equal(b.calls.filter(c => c.url.includes("googleapis.com/youtube/v3/videos")).length, 3);
  assert.equal(b.calls.length, 49);
});


test("health reports missing API key name without exposing secrets", async () => {
  const { env } = makeEnv(); delete env.YOUTUBE_API_KEY;
  const res = await worker.fetch(new Request("https://x/health"), env);
  const body = await res.json();
  assert.equal(body.ready, false); assert.equal(body.missing, "YOUTUBE_API_KEY");
  assert.equal(JSON.stringify(body).includes(secret), false);
  assert.equal(JSON.stringify(body).includes(ghToken), false);
});


test("all RSS failures without prior candidates do not commit or baseline-dispatch", async () => {
  const b = makeEnv(); const restore = configureCron(b, { rssFailure: true });
  try {
    await runScheduled(b.env);
    assert.equal(b.state.has("monitor:snapshot"), false);
    assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 0);
    assert.equal(JSON.parse(b.state.get("monitor:health")).status, "monitor_failed");
  } finally { restore(); }
});

test("partial RSS failure keeps and polls prior candidate while successful feeds proceed", async () => {
  const old = "priorvideo01"; const state = new Map([["monitor:snapshot", JSON.stringify({ candidates: [{ id: old, channelId: B, title: "MVCI prior", published: "2026-10-16T10:00:00Z", publishedAt: Date.parse("2026-10-16T10:00:00Z"), lifecycle: "live", current: true }] })]]);
  const b = makeEnv({ configValue: { channels: [{ id: A, enabled: true }, { id: B, enabled: true }] }, state });
  globalThis.fetch = async (url, init = {}) => {
    b.calls.push({ url: String(url), init }); const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify({ channels: [{ id: A, enabled: true }, { id: B, enabled: true }] }), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return new URL(u).searchParams.get("channel_id") === B ? new Response("", { status: 503 }) : new Response(monitorFeed(A, "freshvideo01", "MVCI fresh"), { status: 200 });
    if (u.includes("googleapis.com/youtube/v3/videos")) {
      const requested = new URL(u).searchParams.get("id").split(",");
      return new Response(JSON.stringify({ items: requested.map(id => id === old ? { id, snippet: { title: "MVCI prior", liveBroadcastContent: "none" }, liveStreamingDetails: { actualStartTime: "2026-10-16T10:00:00Z", actualEndTime: "2026-10-17T10:00:00Z" } } : { id, snippet: { title: "MVCI fresh", liveBroadcastContent: "none" }, liveStreamingDetails: {} }) }), { status: 200 });
    }
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    throw new Error("unexpected fetch destination");
  };
  await runScheduled(b.env);
  const snapshot = JSON.parse(state.get("monitor:snapshot"));
  assert.equal(JSON.parse(state.get("monitor:health")).status, "partial");
  assert.ok(snapshot.candidates.some(x => x.id === old && x.lifecycle === "ended"));
  assert.ok(b.calls.some(c => c.url.includes("googleapis.com/youtube/v3/videos") && new URL(c.url).searchParams.get("id").includes(old)));
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
});

test("disabled and newly excluded prior candidates are removed once", async () => {
  const state = new Map([["monitor:snapshot", JSON.stringify({ candidates: [
    { id: "disabled001", channelId: B, title: "MVCI old", published: "2026-10-16T10:00:00Z", publishedAt: 1, lifecycle: "live", current: false },
    { id: "excluded001", channelId: A, title: "MVCI old", published: "2026-10-16T10:00:00Z", publishedAt: 1, lifecycle: "upcoming", current: true }
  ] })]]);
  const b = makeEnv({ configValue: { keywords: ["MVCI"], exclude_keywords: ["old"], channels: [{ id: A, enabled: true }, { id: B, enabled: false }] }, state });
  globalThis.fetch = async (url, init = {}) => {
    b.calls.push({ url: String(url), init }); const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify({ keywords: ["MVCI"], exclude_keywords: ["old"], channels: [{ id: A, enabled: true }] }), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return new Response(`<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"></feed>`, { status: 200 });
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    throw new Error("unexpected fetch destination");
  };
  await runScheduled(b.env);
  assert.equal(JSON.parse(state.get("monitor:snapshot")).candidates.length, 0);
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
  b.calls.length = 0; await runScheduled(b.env);
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 0);
});

test("YouTube API title exclusion overrides the eligible RSS title", async () => {
  const state = new Map([["monitor:snapshot", JSON.stringify({ candidates: [{ id: VIDEO, channelId: A, title: "MVCI old", published: "2026-10-16T10:00:00Z", publishedAt: 1, lifecycle: "upcoming", current: true }] })]]);
  const b = makeEnv({ configValue: { keywords: ["MVCI"], exclude_keywords: ["replay"], channels: [{ id: A, enabled: true }] }, state });
  globalThis.fetch = async (url, init = {}) => {
    b.calls.push({ url: String(url), init }); const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify({ keywords: ["MVCI"], exclude_keywords: ["replay"], channels: [{ id: A, enabled: true }] }), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return new Response(monitorFeed(A, VIDEO, "MVCI live"), { status: 200 });
    if (u.includes("googleapis.com/youtube/v3/videos")) return new Response(JSON.stringify({ items: [{ id: VIDEO, snippet: { title: "MVCI replay", liveBroadcastContent: "none" }, liveStreamingDetails: {} }] }), { status: 200 });
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    throw new Error("unexpected fetch destination");
  };
  await runScheduled(b.env);
  assert.equal(JSON.parse(state.get("monitor:snapshot")).candidates.length, 0);
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
});


test("API title exclusion removes a prior candidate even when its RSS feed fails", async () => {
  const state = new Map([["monitor:snapshot", JSON.stringify({ candidates: [{ id: VIDEO, channelId: A, title: "MVCI prior", published: "2026-10-16T10:00:00Z", publishedAt: 1, lifecycle: "live", current: true }] })]]);
  const b = makeEnv({ configValue: { keywords: ["MVCI"], exclude_keywords: ["replay"], channels: [{ id: A, enabled: true }] }, state });
  globalThis.fetch = async (url, init = {}) => {
    b.calls.push({ url: String(url), init }); const u = String(url);
    if (u.includes("raw.githubusercontent.com")) return new Response(JSON.stringify({ keywords: ["MVCI"], exclude_keywords: ["replay"], channels: [{ id: A, enabled: true }] }), { status: 200 });
    if (u.includes("youtube.com/xml/feeds/videos.xml?channel_id=")) return new Response("", { status: 503 });
    if (u.includes("googleapis.com/youtube/v3/videos")) return new Response(JSON.stringify({ items: [{ id: VIDEO, snippet: { title: "MVCI replay", liveBroadcastContent: "none" }, liveStreamingDetails: {} }] }), { status: 200 });
    if (u.includes("api.github.com")) return new Response(null, { status: 204 });
    if (u.includes("pubsubhubbub")) return new Response("", { status: 202 });
    throw new Error("unexpected fetch destination");
  };
  await runScheduled(b.env);
  assert.equal(JSON.parse(state.get("monitor:snapshot")).candidates.length, 0);
  assert.equal(JSON.parse(state.get("monitor:health")).status, "partial");
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 1);
  b.calls.length = 0; await runScheduled(b.env);
  assert.equal(b.calls.filter(c => c.url.includes("api.github.com")).length, 0);
});
