const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "application-metrics.js"), "utf8");
const window = {};
vm.runInNewContext(source, { window });
const { summarize } = window.AlinhaApplicationMetrics;

test("counts applications by selected month and by day", () => {
  const applications = [
    { appliedOn: "2026-09-30", responseReceived: true },
    { appliedOn: "2026-10-01", responseReceived: false },
    { appliedOn: "2026-10-01", responseReceived: true },
    { appliedOn: "2026-10-02", responseReceived: false },
  ];
  const october = summarize(applications, "2026-10");
  assert.equal(october.total, 4);
  assert.equal(october.periodTotal, 3);
  assert.equal(october.responses, 1);
  assert.equal(october.responseRate, 33);
  assert.equal(october.activeDays, 2);
  assert.deepEqual(Array.from(october.daily, (item) => [item.date, item.count]), [["2026-10-02", 1], ["2026-10-01", 2]]);
  assert.deepEqual(Array.from(october.monthly, (item) => [item.month, item.count]), [["2026-10", 3], ["2026-09", 1]]);
});

test("saved jobs appear in records but do not inflate application counts", () => {
  const result = summarize([
    { appliedOn: "2026-10-02", status: "saved", responseReceived: false },
    { appliedOn: "2026-10-02", status: "applied", responseReceived: true },
  ], "2026-10");
  assert.equal(result.total, 1);
  assert.equal(result.periodSaved, 1);
  assert.equal(result.period.length, 2);
  assert.equal(result.responses, 1);
});
