const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "roadmap-keywords.js"), "utf8");

function createKeywords() {
  const data = new Map();
  const sessionStorage = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
  const window = {};
  vm.runInNewContext(source, { window, sessionStorage });
  return { keywords: window.AlinhaRoadmapKeywords, data };
}

test("merges only new selected terms into résumé skills", () => {
  const { keywords } = createKeywords();
  const result = keywords.mergeSkills("SQL\nDocker", ["sql", "APIs REST", "Docker", "HTTP"]);
  assert.equal(result.value, "SQL\nDocker\nAPIs REST\nHTTP");
  assert.deepEqual(Array.from(result.added), ["APIs REST", "HTTP"]);
  assert.throws(() => keywords.mergeSkills("12345", ["Long skill"], 6), /limite/);
});

test("keeps a selected route transfer until it is applied", () => {
  const { keywords } = createKeywords();
  keywords.savePending("backend", "Backend", ["SQL", "sql", "APIs REST"]);
  const pending = keywords.readPending();
  assert.equal(pending.roadmapId, "backend");
  assert.deepEqual(Array.from(pending.terms), ["SQL", "APIs REST"]);
  keywords.clearPending();
  assert.equal(keywords.readPending(), null);
});
