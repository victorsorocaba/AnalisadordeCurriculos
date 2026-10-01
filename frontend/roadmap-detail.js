const roadmapId = decodeURIComponent(location.pathname.split("/").filter(Boolean).at(-1) || "");
const detail = {
  title: document.getElementById("study-title"),
  breadcrumb: document.getElementById("breadcrumb-title"),
  category: document.getElementById("study-category"),
  count: document.getElementById("study-count"),
  percent: document.getElementById("study-percent"),
  progress: document.getElementById("study-progress"),
  fill: document.getElementById("study-progress-fill"),
  original: document.getElementById("study-original"),
  message: document.getElementById("study-message"),
  sections: document.getElementById("study-sections"),
};

function updateProgress(data, progress) {
  const selected = new Set(progress[roadmapId] || []);
  const ids = data.sections.flatMap((section) => section.topics.map((topic) => topic.id));
  const done = ids.filter((id) => selected.has(id)).length;
  const percent = Math.round(done / ids.length * 100);
  detail.count.textContent = `${done} de ${ids.length} assuntos concluídos`;
  detail.percent.textContent = `${percent}%`;
  detail.progress.setAttribute("aria-valuenow", String(percent));
  detail.fill.style.width = `${percent}%`;
  detail.message.textContent = done === ids.length ? "Rota concluída! Continue praticando para consolidar o aprendizado." : done ? "Progresso salvo. Continue de onde parou." : "Comece pelo primeiro assunto e avance no seu ritmo.";
}

function renderSections(data, progress) {
  const selected = new Set(progress[roadmapId] || []);
  const sections = data.sections.map((section, index) => {
    const wrapper = document.createElement("section");
    wrapper.className = "study-phase";
    const header = document.createElement("div");
    header.className = "study-phase-header";
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const heading = document.createElement("h2");
    heading.textContent = section.title;
    header.append(number, heading);
    const list = document.createElement("div");
    list.className = "study-topic-list";
    for (const topic of section.topics) {
      const label = document.createElement("label");
      label.className = "study-topic";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selected.has(topic.id);
      checkbox.setAttribute("aria-label", `Aprendi: ${topic.title}`);
      const text = document.createElement("span");
      text.textContent = topic.title;
      label.classList.toggle("is-complete", checkbox.checked);
      checkbox.addEventListener("change", async () => {
        checkbox.disabled = true;
        const checked = checkbox.checked;
        try {
          progress = await AlinhaStorage.setTopic(roadmapId, topic.id, checked);
          label.classList.toggle("is-complete", checked);
          updateProgress(data, progress);
        } catch (error) {
          checkbox.checked = !checked;
          detail.message.textContent = `Não foi possível salvar: ${error.message}`;
        } finally { checkbox.disabled = false; }
      });
      label.append(checkbox, text);
      list.append(label);
    }
    wrapper.append(header, list);
    return wrapper;
  });
  detail.sections.replaceChildren(...sections);
  updateProgress(data, progress);
}

Promise.all([
  fetch("/assets/roadmaps.json").then((response) => response.json()),
  fetch("/assets/study-topics.json").then((response) => response.json()),
  AlinhaStorage.readyTopics(),
]).then(([catalog, content, progress]) => {
  const roadmap = catalog.roadmaps.find((item) => item.id === roadmapId);
  const data = content.roadmaps[roadmapId];
  if (!roadmap || !data) throw new Error("Esta rota não foi encontrada.");
  document.title = `${roadmap.title} — Rotas de estudo | Alinha`;
  detail.title.textContent = roadmap.title;
  detail.breadcrumb.textContent = roadmap.title;
  detail.category.textContent = roadmap.category.toUpperCase();
  detail.original.href = roadmap.url;
  renderSections(data, progress);
}).catch((error) => {
  detail.title.textContent = "Não foi possível carregar a rota";
  detail.message.textContent = error.message;
});
