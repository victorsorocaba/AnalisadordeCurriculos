const ROADMAPS_STORAGE_KEY = "alinha-roadmaps-v1";
const ROADMAPS_PAGE_SIZE = 18;
const ROADMAP_STATUS_LABELS = {
  saved: "Quero estudar",
  studying: "Estudando",
  completed: "Concluída",
};

const roadmapElements = {
  search: document.getElementById("roadmaps-search"),
  category: document.getElementById("roadmaps-category"),
  progressFilter: document.getElementById("roadmaps-progress-filter"),
  list: document.getElementById("roadmaps-list"),
  results: document.getElementById("roadmaps-results"),
  summary: document.getElementById("roadmaps-progress-summary"),
  total: document.getElementById("roadmaps-total"),
  more: document.getElementById("roadmaps-more"),
};

let roadmapCatalog = [];
let roadmapVisibleCount = ROADMAPS_PAGE_SIZE;
let roadmapTopics = {};
let topicProgress = {};

function readRoadmapProgress() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ROADMAPS_STORAGE_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(([id, status]) =>
        /^[a-z0-9-]+$/.test(id) && Object.hasOwn(ROADMAP_STATUS_LABELS, status)
      )
    );
  } catch {
    return {};
  }
}

let roadmapProgress = readRoadmapProgress();

function saveRoadmapProgress() {
  try {
    localStorage.setItem(ROADMAPS_STORAGE_KEY, JSON.stringify(roadmapProgress));
    return true;
  } catch {
    roadmapElements.results.textContent = "Não foi possível salvar o planejamento neste navegador.";
    return false;
  }
}

function normalizeRoadmapText(value) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
}

function filteredRoadmaps() {
  const query = normalizeRoadmapText(roadmapElements.search.value.trim());
  const category = roadmapElements.category.value;
  const status = roadmapElements.progressFilter.value;
  return roadmapCatalog.filter((roadmap) =>
    (category === "all" || roadmap.category === category) &&
    (status === "all" || roadmapProgress[roadmap.id] === status) &&
    (!query || normalizeRoadmapText(`${roadmap.title} ${roadmap.category}`).includes(query))
  );
}

function updateRoadmapSummary(shown, total) {
  roadmapElements.results.textContent = `${total} ${total === 1 ? "rota encontrada" : "rotas encontradas"}${shown < total ? ` · exibindo ${shown}` : ""}`;
  const counts = { saved: 0, studying: 0, completed: 0 };
  for (const roadmap of roadmapCatalog) {
    const status = roadmapProgress[roadmap.id];
    if (Object.hasOwn(counts, status)) counts[status] += 1;
  }
  roadmapElements.summary.textContent = `${counts.saved} quero estudar · ${counts.studying} estudando · ${counts.completed} concluídas`;
}

function roadmapCard(roadmap) {
  const card = document.createElement("article");
  card.className = "roadmap-card";
  card.dataset.status = roadmapProgress[roadmap.id] || "";

  const header = document.createElement("div");
  header.className = "roadmap-card-header";
  const icon = document.createElement("span");
  icon.className = "roadmap-card-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = roadmap.category === "Carreiras" ? "◈" : roadmap.category === "Habilidades" ? "◇" : roadmap.category === "Iniciantes" ? "✳" : "✓";
  const type = document.createElement("span");
  type.className = "roadmap-card-category";
  type.textContent = roadmap.category === "Práticas" ? "Boas práticas" : roadmap.category;
  header.append(icon, type);

  const title = document.createElement("h3");
  const titleLink = document.createElement("a");
  titleLink.href = `/rotas-estudo/${encodeURIComponent(roadmap.id)}`;
  titleLink.textContent = roadmap.title;
  title.append(titleLink);
  const topicIds = roadmapTopics[roadmap.id] || [];
  const completed = new Set(topicProgress[roadmap.id] || []);
  const done = topicIds.filter((id) => completed.has(id)).length;
  const allTopicsDone = topicIds.length > 0 && done === topicIds.length;
  const topicSummary = document.createElement("div");
  topicSummary.className = "roadmap-topic-summary";
  topicSummary.textContent = topicIds.length ? `${done} de ${topicIds.length} assuntos aprendidos` : "Abra a rota para começar";
  const topicTrack = document.createElement("div");
  topicTrack.className = "roadmap-topic-track";
  const topicFill = document.createElement("span");
  topicFill.style.width = topicIds.length ? `${Math.round(done / topicIds.length * 100)}%` : "0%";
  topicTrack.append(topicFill);
  const footer = document.createElement("div");
  footer.className = "roadmap-card-footer";
  const link = document.createElement("a");
  link.href = `/rotas-estudo/${encodeURIComponent(roadmap.id)}`;
  link.textContent = roadmapProgress[roadmap.id] === "completed" || allTopicsDone ? "Adicionar ao currículo →" : "Ver assuntos →";

  const label = document.createElement("label");
  label.className = "roadmap-status-label";
  const labelText = document.createElement("span");
  labelText.className = "visually-hidden";
  labelText.textContent = `Planejamento da rota ${roadmap.title}`;
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Planejamento da rota ${roadmap.title}`);
  for (const [value, text] of Object.entries({ "": "Planejar", ...ROADMAP_STATUS_LABELS })) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    select.append(option);
  }
  select.value = roadmapProgress[roadmap.id] || "";
  select.addEventListener("change", async () => {
    const previous = roadmapProgress[roadmap.id];
    select.disabled = true;
    try { await AlinhaStorage.setRoadmap(roadmap.id, select.value); }
    catch (error) {
      select.value = previous || "";
      roadmapElements.results.textContent = error.message;
      select.disabled = false;
      return;
    }
    select.disabled = false;
    if (select.value) roadmapProgress[roadmap.id] = select.value;
    else delete roadmapProgress[roadmap.id];
    if (!saveRoadmapProgress()) {
      if (previous) roadmapProgress[roadmap.id] = previous;
      else delete roadmapProgress[roadmap.id];
      select.value = previous || "";
      return;
    }
    card.dataset.status = select.value;
    link.textContent = select.value === "completed" || allTopicsDone ? "Adicionar ao currículo →" : "Ver assuntos →";
    if (roadmapElements.progressFilter.value !== "all") renderRoadmaps();
    else updateRoadmapSummary(Math.min(roadmapVisibleCount, filteredRoadmaps().length), filteredRoadmaps().length);
  });
  label.append(labelText, select);
  footer.append(link, label);
  card.append(header, title, topicSummary, topicTrack, footer);
  return card;
}

function renderRoadmaps() {
  const filtered = filteredRoadmaps();
  const visible = filtered.slice(0, roadmapVisibleCount);
  roadmapElements.list.replaceChildren(...visible.map(roadmapCard));
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "roadmaps-empty";
    empty.textContent = "Nenhuma rota corresponde aos filtros. Tente outro termo ou categoria.";
    roadmapElements.list.append(empty);
  }
  roadmapElements.more.hidden = visible.length >= filtered.length;
  updateRoadmapSummary(visible.length, filtered.length);
}

for (const control of [roadmapElements.search, roadmapElements.category, roadmapElements.progressFilter]) {
  control.addEventListener(control === roadmapElements.search ? "input" : "change", () => {
    roadmapVisibleCount = ROADMAPS_PAGE_SIZE;
    renderRoadmaps();
  });
}

roadmapElements.more.addEventListener("click", () => {
  roadmapVisibleCount += ROADMAPS_PAGE_SIZE;
  renderRoadmaps();
});

AlinhaStorage.readyRoadmaps().then((progress) => {
  if (progress === null) return;
  roadmapProgress = progress;
  renderRoadmaps();
  document.querySelector(".roadmaps-intro p").textContent = "Pesquise por área ou tecnologia. Abra uma rota, marque os assuntos aprendidos e acompanhe seu progresso. Seu planejamento fica salvo no PostgreSQL deste servidor.";
}).catch((error) => {
  document.querySelector(".roadmaps-intro p").textContent = `Não foi possível sincronizar o PostgreSQL: ${error.message}. O planejamento anterior continua neste navegador.`;
});

Promise.all([
  fetch("/assets/roadmaps.json").then((response) => { if (!response.ok) throw new Error("O catálogo de rotas não está disponível."); return response.json(); }),
  fetch("/assets/study-topics.json").then((response) => { if (!response.ok) throw new Error("Os assuntos não estão disponíveis."); return response.json(); }),
  AlinhaStorage.readyTopics(),
])
  .then(([data, topics, progress]) => {
    if (!Array.isArray(data.roadmaps)) throw new Error("O catálogo de rotas está inválido.");
    roadmapTopics = Object.fromEntries(Object.entries(topics.roadmaps).map(([id, route]) => [id, route.sections.flatMap((section) => section.topics.map((topic) => topic.id))]));
    topicProgress = progress;
    roadmapCatalog = data.roadmaps.filter((item) =>
      typeof item.id === "string" && /^[a-z0-9-]+$/.test(item.id) &&
      typeof item.title === "string" && typeof item.category === "string" &&
      item.url === `https://roadmap.sh/${item.id}`
    );
    const categoryOrder = { Iniciantes: 0, Carreiras: 1, Habilidades: 2, Práticas: 3 };
    roadmapCatalog.sort((a, b) => (categoryOrder[a.category] ?? 9) - (categoryOrder[b.category] ?? 9));
    roadmapElements.total.textContent = `${roadmapCatalog.length} rotas`;
    renderRoadmaps();
  })
  .catch((error) => {
    roadmapElements.results.textContent = error.message;
    roadmapElements.list.replaceChildren();
  });
