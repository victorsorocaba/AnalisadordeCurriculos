/* Pure date summaries shared by the dashboard and tests. */
(function () {
  function summarize(applications, selectedMonth = "") {
    const valid = applications.filter((entry) => /^\d{4}-\d{2}-\d{2}$/.test(entry.appliedOn));
    const period = selectedMonth ? valid.filter((entry) => entry.appliedOn.startsWith(`${selectedMonth}-`)) : valid;
    const dailyCounts = new Map();
    const monthlyCounts = new Map();
    for (const entry of valid) {
      const month = entry.appliedOn.slice(0, 7);
      const item = monthlyCounts.get(month) || { month, count: 0, responses: 0 };
      item.count += 1;
      if (entry.responseReceived) item.responses += 1;
      monthlyCounts.set(month, item);
    }
    for (const entry of period) dailyCounts.set(entry.appliedOn, (dailyCounts.get(entry.appliedOn) || 0) + 1);
    const responses = period.filter((entry) => entry.responseReceived).length;
    return {
      total: valid.length,
      periodTotal: period.length,
      responses,
      responseRate: period.length ? Math.round(responses / period.length * 100) : 0,
      activeDays: dailyCounts.size,
      daily: [...dailyCounts].map(([date, count]) => ({ date, count })).sort((a, b) => b.date.localeCompare(a.date)),
      monthly: [...monthlyCounts.values()].sort((a, b) => b.month.localeCompare(a.month)),
      period,
    };
  }

  window.AlinhaApplicationMetrics = { summarize };
}());
