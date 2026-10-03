const test = require("node:test");
const assert = require("node:assert/strict");
const { recommend } = require("../study-recommendations.js");

test("recommends a matching study route and topic from a resume gap", () => {
  const result = recommend(
    ["Falta demonstrar experiência com Python e APIs REST"],
    [{ id: "backend", title: "Backend" }, { id: "frontend", title: "Frontend" }],
    { backend: { sections: [{ topics: [{ title: "Criar APIs REST" }] }] }, frontend: { sections: [] } },
    { backend: ["Python", "APIs REST"], frontend: ["CSS"] },
  );
  assert.equal(result[0].roadmap.id, "backend");
  assert.equal(result[0].topics[0].title, "Criar APIs REST");
  assert.equal(result.some((item) => item.roadmap.id === "frontend"), false);
});
