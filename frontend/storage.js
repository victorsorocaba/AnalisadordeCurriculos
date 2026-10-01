/* PostgreSQL sync. Existing browser data is imported once and retained as a local cache. */
(function () {
  const KEY = "alinha-profile-key-v1";
  const VERSIONS = "alinha-versions-v1";
  const ROADMAPS = "alinha-roadmaps-v1";
  const TOPICS = "alinha-topic-progress-v1";
  let enabled = false;
  let checked = false;
  let versionsPromise;
  let roadmapsPromise;
  let topicsPromise;

  function profileKey() {
    let value = localStorage.getItem(KEY);
    if (!value) {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      value = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
      localStorage.setItem(KEY, value);
    }
    return value;
  }

  async function status() {
    if (checked) return enabled;
    const response = await fetch("/api/storage/status");
    if (!response.ok) throw new Error("Não foi possível verificar o armazenamento.");
    enabled = Boolean((await response.json()).enabled);
    checked = true;
    return enabled;
  }

  async function request(path, method = "GET", body) {
    const response = await fetch(`/api/storage${path}`, {
      method,
      headers: { "X-Profile-Key": profileKey(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      let detail = "Não foi possível salvar no banco de dados.";
      try { const data = await response.json(); if (typeof data.detail === "string") detail = data.detail; } catch { /* Use default. */ }
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  async function loadVersions() {
    if (!await status()) return null;
    if (localStorage.getItem(`${VERSIONS}-imported`) !== "1") {
      const local = JSON.parse(localStorage.getItem(VERSIONS) || "[]");
      if (Array.isArray(local)) for (const entry of local) await request("/versions", "POST", entry);
      localStorage.setItem(`${VERSIONS}-imported`, "1");
    }
    const versions = await request("/versions");
    localStorage.setItem(VERSIONS, JSON.stringify(versions));
    return versions;
  }

  function readyVersions() {
    return versionsPromise ||= loadVersions();
  }

  async function saveVersion(entry) {
    await readyVersions();
    if (enabled) await request("/versions", "POST", entry);
  }

  async function deleteVersion(id) {
    await readyVersions();
    if (enabled) await request(`/versions/${encodeURIComponent(id)}`, "DELETE");
  }

  async function loadRoadmaps() {
    if (!await status()) return null;
    if (localStorage.getItem(`${ROADMAPS}-imported`) !== "1") {
      const local = JSON.parse(localStorage.getItem(ROADMAPS) || "{}");
      await request("/roadmaps", "PUT", local);
      localStorage.setItem(`${ROADMAPS}-imported`, "1");
    }
    const progress = await request("/roadmaps");
    localStorage.setItem(ROADMAPS, JSON.stringify(progress));
    return progress;
  }

  function readyRoadmaps() {
    return roadmapsPromise ||= loadRoadmaps();
  }

  async function setRoadmap(id, value) {
    await readyRoadmaps();
    if (!enabled) return;
    const path = `/roadmaps/${encodeURIComponent(id)}`;
    if (value) await request(path, "PUT", { status: value });
    else await request(path, "DELETE");
  }

  function localTopics() {
    try {
      const value = JSON.parse(localStorage.getItem(TOPICS) || "{}");
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    } catch { return {}; }
  }

  async function loadTopics() {
    if (!await status()) return localTopics();
    if (localStorage.getItem(`${TOPICS}-imported`) !== "1") {
      await request("/topics", "PUT", localTopics());
      localStorage.setItem(`${TOPICS}-imported`, "1");
    }
    const progress = await request("/topics");
    localStorage.setItem(TOPICS, JSON.stringify(progress));
    return progress;
  }

  function readyTopics() {
    return topicsPromise ||= loadTopics();
  }

  async function setTopic(roadmapId, topicId, checked) {
    const progress = await readyTopics();
    if (enabled) {
      const path = `/topics/${encodeURIComponent(roadmapId)}/${encodeURIComponent(topicId)}`;
      await request(path, checked ? "PUT" : "DELETE");
    }
    const selected = new Set(Array.isArray(progress[roadmapId]) ? progress[roadmapId] : []);
    if (checked) selected.add(topicId);
    else selected.delete(topicId);
    if (selected.size) progress[roadmapId] = [...selected];
    else delete progress[roadmapId];
    localStorage.setItem(TOPICS, JSON.stringify(progress));
    return progress;
  }

  window.AlinhaStorage = { readyVersions, saveVersion, deleteVersion, readyRoadmaps, setRoadmap, readyTopics, setTopic, get enabled() { return enabled; } };
}());
