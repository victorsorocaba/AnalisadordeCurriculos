const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");

const source = fs.readFileSync(path.join(__dirname, "..", "storage.js"), "utf8");

function environment(initial, fetch) {
  const values = new Map(Object.entries(initial));
  const localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
  const window = {};
  vm.runInNewContext(source, { window, localStorage, crypto: crypto.webcrypto, btoa, fetch });
  return { storage: window.AlinhaStorage, values };
}

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}

test("imports previous browser versions once and keeps a local copy", async () => {
  const old = [{ id: "old-version", label: "Vaga anterior" }];
  const requests = [];
  const { storage, values } = environment({ "alinha-versions-v1": JSON.stringify(old) }, async (url, options = {}) => {
    requests.push([url, options.method || "GET"]);
    if (url.endsWith("/status")) return response({ enabled: true });
    if (options.method === "POST") return response({ id: "old-version" }, 201);
    return response(old);
  });
  assert.equal((await storage.readyVersions())[0].id, "old-version");
  assert.equal(values.get("alinha-versions-v1-imported"), "1");
  await storage.readyVersions();
  assert.equal(requests.filter(([, method]) => method === "POST").length, 1);
  assert.equal(requests[1][0], "/api/storage/versions");
  assert.equal(JSON.parse(values.get("alinha-versions-v1"))[0].id, "old-version");
});

test("account session switches profiles without importing another browser cache", async () => {
  const requests = [];
  const { storage, values } = environment({ "alinha-versions-v1": '[{"id":"local"}]' }, async (url, options = {}) => {
    requests.push([url, options]);
    if (url.endsWith("/status")) return response({ enabled: true });
    return response([]);
  });
  storage.setSession("session-secret");
  assert.equal(values.has("alinha-versions-v1"), false);
  assert.deepEqual(await storage.readyVersions(), []);
  assert.equal(requests.filter(([, options]) => options.method === "POST").length, 0);
  assert.equal(requests.at(-1)[1].headers["X-Session-Token"], "session-secret");
});

test("failed import retains browser data and does not mark it complete", async () => {
  const old = [{ id: "old-version" }];
  const { storage, values } = environment({ "alinha-versions-v1": JSON.stringify(old) }, async (url, options = {}) => {
    if (url.endsWith("/status")) return response({ enabled: true });
    if (options.method === "POST") return response({ detail: "Banco indisponível" }, 503);
    return response([]);
  });
  await assert.rejects(storage.readyVersions(), /Banco indisponível/);
  assert.equal(values.get("alinha-versions-v1-imported"), undefined);
  assert.deepEqual(JSON.parse(values.get("alinha-versions-v1")), old);
});

test("imports roadmap progress and saves later changes to the server", async () => {
  const requests = [];
  const { storage, values } = environment({ "alinha-roadmaps-v1": '{"frontend":"studying"}' }, async (url, options = {}) => {
    requests.push([url, options.method || "GET", options.body]);
    if (url.endsWith("/status")) return response({ enabled: true });
    if (options.method === "PUT") return response({ imported: 1 });
    return response({ frontend: "studying" });
  });
  assert.equal((await storage.readyRoadmaps()).frontend, "studying");
  await storage.setRoadmap("frontend", "completed");
  assert.equal(values.get("alinha-roadmaps-v1-imported"), "1");
  assert.equal(requests.at(-1)[0], "/api/storage/roadmaps/frontend");
  assert.equal(requests.at(-1)[2], '{"status":"completed"}');
});

test("imports checked topics and saves marking and unmarking", async () => {
  const requests = [];
  const initial = { backend: ["abc123"] };
  const { storage, values } = environment({ "alinha-topic-progress-v1": JSON.stringify(initial) }, async (url, options = {}) => {
    requests.push([url, options.method || "GET", options.body]);
    if (url.endsWith("/status")) return response({ enabled: true });
    if (url === "/api/storage/topics" && options.method === "GET") return response(initial);
    if (options.method === "DELETE") return response(null, 204);
    return response({ completed: true });
  });
  assert.equal((await storage.readyTopics()).backend[0], "abc123");
  assert.equal(values.get("alinha-topic-progress-v1-imported"), "1");
  await storage.setTopic("backend", "def456", true);
  assert.deepEqual(JSON.parse(values.get("alinha-topic-progress-v1")).backend, ["abc123", "def456"]);
  await storage.setTopic("backend", "abc123", false);
  assert.deepEqual(JSON.parse(values.get("alinha-topic-progress-v1")).backend, ["def456"]);
  assert.equal(requests.filter(([, method]) => method === "PUT").length, 2);
  assert.equal(requests.at(-1)[1], "DELETE");
});

test("application history imports once and writes changes to the server", async () => {
  const old = { id: "old-id", company: "Acme", role: "Dev", source: "LinkedIn", appliedOn: "2026-09-25", vacancyUrl: "", responseReceived: false, notes: "" };
  const requests = [];
  const { storage, values } = environment({ "alinha-applications-v1": JSON.stringify([old]) }, async (url, options = {}) => {
    requests.push([url, options.method || "GET", options.body]);
    if (url.endsWith("/status")) return response({ enabled: true });
    if (url === "/api/storage/applications" && options.method === "PUT") return response({ imported: 1 });
    if (url === "/api/storage/applications" && options.method === "GET") return response([old]);
    if (url === "/api/storage/applications" && options.method === "POST") return response({ ...JSON.parse(options.body), id: "new-id" }, 201);
    if (url.endsWith("/old-id") && options.method === "PUT") return response({ ...JSON.parse(options.body), id: "old-id" });
    return response(null, 204);
  });
  assert.equal((await storage.readyApplications()).length, 1);
  const next = { company: "Beta", role: "QA", source: "Gupy", appliedOn: "2026-10-02", vacancyUrl: "", responseReceived: false, notes: "" };
  await storage.saveApplication(next);
  await storage.updateApplication("old-id", { ...old, responseReceived: true });
  await storage.deleteApplication("new-id");
  assert.equal(values.get("alinha-applications-v1-imported"), "1");
  assert.equal(JSON.parse(values.get("alinha-applications-v1")).length, 1);
  assert.equal(JSON.parse(values.get("alinha-applications-v1"))[0].responseReceived, true);
  assert.equal(requests.filter(([, method]) => method === "PUT").length, 2);
  assert.equal(JSON.parse(requests.find(([url, method]) => url === "/api/storage/applications" && method === "PUT")[2])[0].vacancyUrl, null);
  assert.equal(requests.at(-1)[1], "DELETE");
});
