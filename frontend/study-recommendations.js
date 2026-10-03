(function (root) {
  const IGNORE = new Set(["para", "como", "com", "uma", "um", "de", "da", "do", "das", "dos", "nos", "nas", "the", "and", "for", "you", "que", "ter", "por", "experiencia", "experiência", "conhecimento", "habilidade", "requisito", "em", "na", "no"]);
  const normalize = (value) => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const tokens = (value) => [...new Set(normalize(value).match(/[a-z0-9+#.]{3,}/g) || [])].filter((item) => !IGNORE.has(item));

  function recommend(gaps, catalog, topics, keywords, limit = 4) {
    const gapText = normalize(gaps.join(" "));
    const gapTokens = new Set(tokens(gapText));
    return catalog.map((roadmap) => {
      const routeKeywords = keywords[roadmap.id] || [];
      const routeTopics = (topics[roadmap.id]?.sections || []).flatMap((section) => section.topics || []);
      let score = 0;
      const matched = [];
      for (const term of [roadmap.title, ...routeKeywords]) {
        const termText = normalize(term);
        if (termText.length >= 3 && gapText.includes(termText)) { score += 5; matched.push(term); }
      }
      if (!score) {
        const routeTokens = new Set(tokens(`${roadmap.title} ${routeKeywords.join(" ")}`));
        for (const term of routeTokens) if (gapTokens.has(term)) score += 2;
      }
      const matchedTopics = routeTopics.filter((topic) => tokens(topic.title).some((term) => gapTokens.has(term))).slice(0, 2);
      score += matchedTopics.length;
      return { roadmap, score, matched: [...new Set(matched)].slice(0, 3), topics: matchedTopics };
    }).filter((entry) => entry.score >= 2).sort((a, b) => b.score - a.score || a.roadmap.title.localeCompare(b.roadmap.title)).slice(0, limit);
  }

  async function load(gaps) {
    const [catalog, topics, keywords] = await Promise.all([
      fetch("/assets/roadmaps.json").then((response) => response.json()),
      fetch("/assets/study-topics.json").then((response) => response.json()),
      fetch("/assets/study-keywords.json").then((response) => response.json()),
    ]);
    return recommend(gaps, catalog.roadmaps, topics.roadmaps, keywords);
  }

  root.AlinhaStudyRecommendations = { recommend, load };
  if (typeof module !== "undefined") module.exports = { recommend, normalize, tokens };
})(typeof window !== "undefined" ? window : globalThis);
