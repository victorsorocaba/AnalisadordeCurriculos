/* Cross-page transfer of completed-route skills into the editable résumé. */
(function () {
  const PENDING_KEY = "alinha-roadmap-keywords-pending-v1";
  const WORKING_KEY = "alinha-working-analysis-v1";

  function cleanTerms(terms) {
    if (!Array.isArray(terms)) return [];
    const seen = new Set();
    return terms.slice(0, 12).filter((value) => typeof value === "string").map((value) => value.trim()).filter((value) => {
      const key = value.toLocaleLowerCase("pt-BR");
      if (!value || value.length > 80 || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function readPending() {
    try {
      const parsed = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
      if (!parsed || !/^[a-z0-9-]{1,100}$/.test(parsed.roadmapId)) return null;
      const terms = cleanTerms(parsed.terms);
      return terms.length ? { roadmapId: parsed.roadmapId, title: String(parsed.title || "Rota de estudo").slice(0, 100), terms } : null;
    } catch { return null; }
  }

  function savePending(roadmapId, title, terms) {
    if (!/^[a-z0-9-]{1,100}$/.test(roadmapId)) throw new Error("Rota inválida.");
    const cleaned = cleanTerms(terms);
    if (!cleaned.length) throw new Error("Selecione ao menos uma palavra-chave.");
    sessionStorage.setItem(PENDING_KEY, JSON.stringify({ roadmapId, title, terms: cleaned }));
  }

  function mergeSkills(existing, terms, maxLength = 5000) {
    const lines = String(existing || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const seen = new Set(lines.map((line) => line.toLocaleLowerCase("pt-BR")));
    const added = [];
    for (const term of cleanTerms(terms)) {
      const key = term.toLocaleLowerCase("pt-BR");
      if (seen.has(key)) continue;
      const candidate = [...lines, term].join("\n");
      if (candidate.length > maxLength) throw new Error("O campo Habilidades atingiu o limite de caracteres. Remova algum item antes de importar.");
      lines.push(term);
      seen.add(key);
      added.push(term);
    }
    return { value: lines.join("\n"), added };
  }

  window.AlinhaRoadmapKeywords = {
    cleanTerms, readPending, savePending, mergeSkills,
    clearPending() { sessionStorage.removeItem(PENDING_KEY); },
    saveWorking(value) { sessionStorage.setItem(WORKING_KEY, JSON.stringify(value)); },
    readWorking() {
      try { return JSON.parse(sessionStorage.getItem(WORKING_KEY) || "null"); }
      catch { return null; }
    },
    clearWorking() { sessionStorage.removeItem(WORKING_KEY); },
  };
}());
