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
  const env = { STATE: kv, WORKER_URL: "https://mvci-feed-trigger.workers.dev", GITHUB_TOKEN: ghToken, HUB_SECRET: secret, WEBHOOK_TOKEN: secret, state };
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

test("cron attempts GitHub dispatch even when subscription renewal fails", async () => {
  const { env, calls } = makeEnv();
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("raw.githubusercontent.com")) return new Response(JSON.stringify(config), { status: 200 });
    if (String(url).includes("pubsubhubbub")) return new Response("", { status: 503 });
    if (String(url).includes("api.github.com")) return new Response(null, { status: 200 });
    throw new Error("unexpected destination");
  };
  let job; await worker.scheduled({}, env, { waitUntil(p) { job = p; } }); await job;
  assert.equal(calls.filter(c => c.url.includes("pubsubhubbub")).length, 1);
  assert.equal(calls.filter(c => c.url.includes("api.github.com")).length, 1);
});

test("cron subscription uses exact topic and callback form fields; zero channels still runs dispatch", async () => {
  const { env, calls } = makeEnv({ hubStatus: 204 }); let job;
  await worker.scheduled({}, env, { waitUntil(p) { job = p; } }); await job;
  const req = calls.find(c => c.url.includes("pubsubhubbub")); const params = new URLSearchParams(req.init.body);
  assert.equal(params.get("hub.mode"), "subscribe"); assert.equal(params.get("hub.topic"), `https://www.youtube.com/xml/feeds/videos.xml?channel_id=${A}`);
  assert.equal(params.get("hub.callback"), `https://mvci-feed-trigger.workers.dev/youtube/${secret}`);
  assert.equal(params.get("hub.secret"), secret); assert.equal(params.get("hub.lease_seconds"), "864000"); assert.equal(params.get("hub.verify"), "async");
  const empty = makeEnv({ configValue: { channels: [] } }); job = null;
  await worker.scheduled({}, empty.env, { waitUntil(p) { job = p; } }); await job;
  assert.equal(empty.calls.filter(c => c.url.includes("pubsubhubbub")).length, 0);
  assert.equal(empty.calls.filter(c => c.url.includes("api.github.com")).length, 1);
});
