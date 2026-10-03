/* PostgreSQL sync. Existing browser data is imported once and retained as a local cache. */
(function () {
  const KEY = "alinha-profile-key-v1";
  const VERSIONS = "alinha-versions-v1";
  const ROADMAPS = "alinha-roadmaps-v1";
  const TOPICS = "alinha-topic-progress-v1";
  const APPLICATIONS = "alinha-applications-v1";
  const SESSION = "alinha-session-v1";
  let enabled = false;
  let checked = false;
  let versionsPromise;
  let roadmapsPromise;
  let topicsPromise;
  let applicationsPromise;

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
      headers: { "X-Profile-Key": profileKey(), ...(localStorage.getItem(SESSION) ? { "X-Session-Token": localStorage.getItem(SESSION) } : {}), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
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
    if (!localStorage.getItem(SESSION) && localStorage.getItem(`${VERSIONS}-imported`) !== "1") {
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
    if (!localStorage.getItem(SESSION) && localStorage.getItem(`${ROADMAPS}-imported`) !== "1") {
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
    if (!localStorage.getItem(SESSION) && localStorage.getItem(`${TOPICS}-imported`) !== "1") {
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

  function localApplications() {
    try {
      const value = JSON.parse(localStorage.getItem(APPLICATIONS) || "[]");
      return Array.isArray(value) ? value : [];
    } catch { return []; }
  }

  async function loadApplications() {
    if (!await status()) return localApplications();
    if (!localStorage.getItem(SESSION) && localStorage.getItem(`${APPLICATIONS}-imported`) !== "1") {
      await request("/applications", "PUT", localApplications().map((item) => ({ ...item, vacancyUrl: item.vacancyUrl || null })));
      localStorage.setItem(`${APPLICATIONS}-imported`, "1");
    }
    const applications = await request("/applications");
    localStorage.setItem(APPLICATIONS, JSON.stringify(applications));
    return applications;
  }

  function readyApplications() {
    return applicationsPromise ||= loadApplications();
  }

  async function saveApplication(application) {
    const entries = await readyApplications();
    const payload = { ...application, vacancyUrl: application.vacancyUrl || null };
    const created = enabled
      ? await request("/applications", "POST", payload)
      : { id: crypto.randomUUID(), ...payload };
    entries.unshift(created);
    localStorage.setItem(APPLICATIONS, JSON.stringify(entries));
    return created;
  }

  async function updateApplication(id, application) {
    const entries = await readyApplications();
    const index = entries.findIndex((item) => item.id === id);
    if (index < 0) throw new Error("Candidatura não encontrada.");
    const payload = { ...application, vacancyUrl: application.vacancyUrl || null };
    const updated = enabled
      ? await request(`/applications/${encodeURIComponent(id)}`, "PUT", payload)
      : { id, ...payload };
    entries[index] = updated;
    localStorage.setItem(APPLICATIONS, JSON.stringify(entries));
    return updated;
  }

  async function deleteApplication(id) {
    const entries = await readyApplications();
    if (enabled) await request(`/applications/${encodeURIComponent(id)}`, "DELETE");
    const index = entries.findIndex((item) => item.id === id);
    if (index >= 0) entries.splice(index, 1);
    localStorage.setItem(APPLICATIONS, JSON.stringify(entries));
  }

  function setSession(token) {
    if (token) localStorage.setItem(SESSION, token);
    else localStorage.removeItem(SESSION);
    for (const key of [VERSIONS, ROADMAPS, TOPICS, APPLICATIONS]) {
      localStorage.removeItem(key);
      localStorage.removeItem(`${key}-imported`);
    }
    if (typeof sessionStorage !== "undefined") {
      for (const key of ["alinha-working-analysis-v1", "alinha-roadmap-keywords-pending-v1", "alinha-cert-profile-v1", "alinha-learning-gaps-v1", "alinha-application-prefill-v1"]) sessionStorage.removeItem(key);
    }
    versionsPromise = roadmapsPromise = topicsPromise = applicationsPromise = undefined;
  }

  function sessionToken() { return localStorage.getItem(SESSION) || ""; }

  window.AlinhaStorage = { readyVersions, saveVersion, deleteVersion, readyRoadmaps, setRoadmap, readyTopics, setTopic, readyApplications, saveApplication, updateApplication, deleteApplication, profileKey, setSession, sessionToken, get enabled() { return enabled; } };

  const nav = typeof document !== "undefined" ? document.querySelector(".side-nav") : null;
  if (nav && !nav.querySelector('a[href="/conta"]')) {
    const account = document.createElement("a");
    account.href = "/conta";
    account.className = `nav-link${location.pathname === "/conta" ? " active" : ""}`;
    const icon = document.createElement("span");
    icon.className = "nav-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "◎";
    account.append(icon, document.createTextNode("Minha conta"));
    nav.append(account);
  }
}());
