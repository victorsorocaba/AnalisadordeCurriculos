const MAX_FILE_BYTES = 10 * 1024 * 1024;
const HISTORY_KEY = "alinha-versions-v1";
const fields = [
  ["name", "Nome", false], ["contact", "Contato", false],
  ["headline", "Título profissional", false], ["summary", "Resumo profissional", true],
  ["experience", "Experiência · método STAR", true],
  ["education", "Formação (um item por linha)", true],
  ["skills", "Habilidades (um item por linha)", true],
  ["projects", "Projetos (um item por linha)", true],
];
const $ = (id) => document.getElementById(id);
const form = $("analysis-form");
const fileInput = $("resume");
const dropZone = $("drop-zone");
const jobInput = $("job-description");
const projectsInput = $("projects");
let selectedFile = null;
let analysis = null;
let generatedLatex = "";
let pdfUrl = null;
let lastRenderedDraft = "";
let learningRequest = 0;

async function updateLearningRecommendations(data) {
  const sequence = ++learningRequest;
  const panel = $("learning-recommendations");
  const routes = $("learning-routes");
  const certifications = $("learning-certifications");
  routes.replaceChildren(); certifications.replaceChildren();
  panel.hidden = !data.gaps.length;
  if (!data.gaps.length) return;
  try { sessionStorage.setItem("alinha-learning-gaps-v1", JSON.stringify(data.gaps)); } catch { /* Current analysis remains visible. */ }
  const waiting = document.createElement("p"); waiting.textContent = "Buscando rotas relacionadas aos requisitos..."; routes.append(waiting);
  try {
    const suggestions = await AlinhaStudyRecommendations.load(data.gaps);
    if (sequence !== learningRequest) return;
    routes.replaceChildren();
    if (!suggestions.length) {
      const fallback = document.createElement("a"); fallback.href = "/rotas-estudo"; fallback.textContent = "Explorar todas as rotas de estudo ↗"; routes.append(fallback);
    }
    for (const item of suggestions) {
      const card = document.createElement("div"); card.className = "learning-card";
      const link = document.createElement("a"); link.href = `/rotas-estudo/${encodeURIComponent(item.roadmap.id)}`; link.textContent = `${item.roadmap.title} ↗`;
      const detail = document.createElement("p");
      detail.textContent = item.topics.length ? `Comece por: ${item.topics.map((topic) => topic.title).join("; ")}` : `Termos relacionados: ${item.matched.join(", ") || item.roadmap.title}`;
      card.append(link, detail); routes.append(card);
    }
  } catch { if (sequence === learningRequest) routes.textContent = "Não foi possível carregar as rotas agora."; }
  try {
    const result = await requestJson("/api/certifications/recommend", { method: "POST", body: (() => {
      const form = new FormData(); form.set("goal", data.gaps.join("; ").slice(0, 200)); return form;
    })() });
    if (sequence !== learningRequest) return;
    if (result.recommendations.length) {
      const title = document.createElement("h4"); title.textContent = "Certificações relacionadas"; certifications.append(title);
      for (const item of result.recommendations.slice(0, 3)) {
        const link = document.createElement("a"); link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = `${item.title} ↗`; certifications.append(link);
      }
    }
  } catch { /* Routes remain useful without certification suggestions. */ }
}

function message(id, text) {
  const box = $(id);
  box.textContent = text;
  box.hidden = !text;
  if (text) box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearFile() {
  selectedFile = null;
  fileInput.value = "";
  $("file-title").textContent = "Arraste seu arquivo ou clique para escolher";
  $("file-meta").hidden = true;
}

function setFile(file) {
  message("form-error", "");
  if (!file) return;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!["pdf", "txt"].includes(extension) || !file.size || file.size > MAX_FILE_BYTES) {
    clearFile();
    message("form-error", "Escolha um PDF ou TXT não vazio com até 10 MB.");
    return;
  }
  selectedFile = file;
  $("file-title").textContent = file.name;
  $("file-meta").textContent = `${(file.size / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} KB · Pronto para analisar`;
  $("file-meta").hidden = false;
}

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("keydown", (event) => {
  if (["Enter", " "].includes(event.key)) { event.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
for (const name of ["dragenter", "dragover"]) dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.add("dragover"); });
for (const name of ["dragleave", "drop"]) dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.remove("dragover"); });
dropZone.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));
for (const [input, count] of [[jobInput, "job-count"], [projectsInput, "projects-count"]]) {
  input.addEventListener("input", () => { $(count).textContent = `${input.value.length.toLocaleString("pt-BR")} / 20.000`; });
}

function setLoading(loading) {
  $("submit-button").disabled = loading;
  $("submit-label").textContent = loading ? "Analisando e preparando PDF..." : "Analisar meu currículo";
  form.setAttribute("aria-busy", String(loading));
}

async function requestJson(url, options) {
  let response;
  const headers = new Headers(options.headers || {});
  const token = $("access-token").value.trim();
  if (token) headers.set("X-Access-Token", token);
  try { response = await fetch(url, { ...options, headers }); }
  catch { throw new Error("Não foi possível conectar ao serviço."); }
  let data;
  try { data = await response.json(); }
  catch { throw new Error("O serviço retornou uma resposta inesperada."); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Não foi possível concluir a operação.");
  return data;
}

function appendTextItem(list, primary, secondary = "") {
  const li = document.createElement("li");
  const title = document.createElement("strong");
  title.textContent = primary;
  li.append(title);
  if (secondary) { const text = document.createElement("span"); text.textContent = secondary; li.append(text); }
  list.append(li);
}

function fillList(id, items, emptyText) {
  const list = $(id);
  list.replaceChildren();
  if (!items.length) appendTextItem(list, emptyText);
  else for (const item of items) appendTextItem(list, item);
}

function buildEditor() {
  const container = $("draft-fields");
  container.replaceChildren();
  for (const [key, label, multiline] of fields) {
    const wrapper = document.createElement("div");
    wrapper.className = "editor-field";
    const labelNode = document.createElement("label");
    labelNode.htmlFor = `draft-${key}`;
    labelNode.textContent = label;
    const input = document.createElement(multiline ? "textarea" : "input");
    input.id = `draft-${key}`;
    input.value = analysis.draft[key] || "";
    input.maxLength = { name: 200, contact: 500, headline: 300, summary: 3000, experience: 10000, education: 5000, skills: 5000, projects: 5000 }[key];
    wrapper.append(labelNode);
    if (key === "experience") {
      const help = document.createElement("p");
      help.className = "editor-help";
      help.id = "experience-help";
      help.textContent = "Separe cada emprego com Empresa | Cargo | Período. Abaixo, escreva um tópico por linha: contexto e tarefa, sua ação e o resultado comprovável. Se não houver resultado, mantenha apenas os fatos conhecidos.";
      wrapper.append(help);
      input.setAttribute("aria-describedby", help.id);
    }
    wrapper.append(input);
    container.append(wrapper);
  }
}

function currentDraft() {
  return Object.fromEntries(fields.map(([key]) => [key, $(`draft-${key}`).value]));
}

function applyPendingRoadmapKeywords() {
  const pending = AlinhaRoadmapKeywords.readPending();
  if (!pending || !$('draft-skills')) return false;
  try {
    const field = $('draft-skills');
    const merged = AlinhaRoadmapKeywords.mergeSkills(field.value, pending.terms, field.maxLength);
    field.value = merged.value;
    const text = merged.added.length
      ? `${merged.added.length} ${merged.added.length === 1 ? "palavra-chave adicionada" : "palavras-chave adicionadas"} ao campo Habilidades a partir da rota ${pending.title}. Revise o conteúdo, atualize a prévia e salve uma nova versão.`
      : `As palavras-chave da rota ${pending.title} já estavam no campo Habilidades. Revise o currículo antes de salvar.`;
    $('roadmap-keywords-notice').textContent = text;
    $('roadmap-keywords-notice').hidden = false;
    $('tailor-status').textContent = text;
    AlinhaRoadmapKeywords.clearPending();
    AlinhaRoadmapKeywords.clearWorking();
    return true;
  } catch (error) {
    $('roadmap-keywords-notice').textContent = error.message;
    $('roadmap-keywords-notice').hidden = false;
    return false;
  }
}

function showAnalysis(data, scrollToResults = true) {
  if (!data || !Number.isInteger(data.percentage) || !data.draft || !Array.isArray(data.improvements) || !Array.isArray(data.matches) || !Array.isArray(data.gaps)) {
    throw new Error("A análise retornou dados incompletos.");
  }
  analysis = data;
  $("tailor-status").textContent = "";
  lastRenderedDraft = "";
  generatedLatex = "";
  if (pdfUrl) { URL.revokeObjectURL(pdfUrl); pdfUrl = null; }
  $("pdf-preview").replaceChildren();
  $("preview-status").textContent = "A prévia será gerada a partir desta versão.";
  $("download-pdf").disabled = true;
  $("copy-latex").disabled = true;
  $("download-latex").disabled = true;
  $("latex-code").textContent = "";
  $("score-value").textContent = `${data.percentage}%`;
  $("score-ring").style.setProperty("--score", `${data.percentage}%`);
  fillList("improvements-list", data.improvements, "Nenhuma melhoria específica foi sugerida.");
  const matches = $("matches-list");
  matches.replaceChildren();
  if (!data.matches.length) appendTextItem(matches, "Nenhum trecho foi confirmado automaticamente.");
  else for (const match of data.matches) appendTextItem(matches, match.requirement, `“${match.excerpt}”`);
  fillList("gaps-list", data.gaps, "Nenhum requisito ausente foi identificado.");
  void updateLearningRecommendations(data);
  buildEditor();
  const importedKeywords = applyPendingRoadmapKeywords();
  updateJobsProfile();
  $("results").hidden = false;
  $("details").hidden = false;
  if (importedKeywords) document.querySelector(".editor-heading").scrollIntoView({ behavior: "smooth", block: "start" });
  else if (scrollToResults) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function updatePdf(base64, previewPages) {
  if (pdfUrl) URL.revokeObjectURL(pdfUrl);
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  pdfUrl = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  const container = $("pdf-preview");
  container.replaceChildren();
  for (const [index, page] of previewPages.entries()) {
    const image = document.createElement("img");
    image.src = `data:image/png;base64,${page}`;
    image.alt = `Página ${index + 1} do currículo`;
    image.loading = "eager";
    container.append(image);
  }
  $("download-pdf").disabled = false;
  $("preview-status").textContent = previewPages.length
    ? "PDF compilado. Prévia das primeiras páginas disponível abaixo."
    : "PDF compilado e pronto para baixar; a prévia não pôde ser gerada.";
}

async function refreshPreview() {
  message("render-error", "");
  const button = $("refresh-preview");
  button.disabled = true;
  $("preview-status").textContent = "Compilando PDF...";
  try {
    const draft = currentDraft();
    const rendered = await requestJson("/api/render", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
    });
    analysis.draft = draft;
    generatedLatex = rendered.latex_code;
    lastRenderedDraft = JSON.stringify(draft);
    $("latex-code").textContent = generatedLatex;
    $("copy-latex").disabled = false;
    $("download-latex").disabled = false;
    updatePdf(rendered.pdf_base64, rendered.preview_pages || []);
    return true;
  } catch (error) {
    $("preview-status").textContent = "Prévia indisponível.";
    message("render-error", error.message);
    return false;
  } finally { button.disabled = false; }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message("form-error", "");
  if (!selectedFile) return message("form-error", "Envie seu currículo para continuar.");
  if (!jobInput.value.trim()) return message("form-error", "Cole a descrição da vaga para continuar.");
  $("results").hidden = true;
  $("details").hidden = true;
  const body = new FormData();
  const mime = selectedFile.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "text/plain";
  body.append("resume", new Blob([selectedFile], { type: mime }), selectedFile.name);
  body.append("job_description", jobInput.value);
  if (projectsInput.value.trim()) body.append("projects", projectsInput.value);
  setLoading(true);
  try {
    const data = await requestJson("/api/analyze/detailed", { method: "POST", body });
    showAnalysis(data);
    await refreshPreview();
  } catch (error) { message("form-error", error.message); }
  finally { setLoading(false); }
});

$("refresh-preview").addEventListener("click", refreshPreview);
$("tailor-resume").addEventListener("click", async () => {
  message("render-error", "");
  const status = $("tailor-status");
  if (!analysis) return;
  if (!jobInput.value.trim()) return message("render-error", "Informe a descrição da vaga antes de preparar o currículo.");
  const button = $("tailor-resume");
  button.disabled = true;
  button.textContent = "Preparando currículo...";
  status.textContent = "Adaptando o currículo à vaga...";
  try {
    const tailored = await requestJson("/api/tailor", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft(), job_description: jobInput.value }),
    });
    showAnalysis(tailored, false);
    const rendered = await refreshPreview();
    status.textContent = rendered
      ? "Versão preparada e prévia atualizada. Revise as informações e salve esta versão se desejar."
      : "Versão preparada. Revise as informações e tente atualizar a prévia novamente.";
    document.querySelector(".editor-heading").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    status.textContent = "";
    message("render-error", error.message);
  } finally { button.disabled = false; button.textContent = "Deixar currículo pronto pra vaga"; }
});
$("download-pdf").addEventListener("click", () => { if (pdfUrl) downloadUrl(pdfUrl, "curriculo-alinhado.pdf"); });
function downloadUrl(url, name) {
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
}
$("download-latex").addEventListener("click", () => {
  if (!generatedLatex) return;
  const url = URL.createObjectURL(new Blob([generatedLatex], { type: "text/x-tex;charset=utf-8" }));
  downloadUrl(url, "curriculo-alinhado.tex");
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("copy-latex").addEventListener("click", async () => {
  if (!generatedLatex) return;
  try { await navigator.clipboard.writeText(generatedLatex); $("copy-latex").textContent = "Copiado ✓"; setTimeout(() => { $("copy-latex").textContent = "Copiar código"; }, 2000); }
  catch { message("render-error", "Não foi possível copiar automaticamente. Selecione o código abaixo."); }
});
$("new-analysis").addEventListener("click", () => {
  $("results").hidden = true; $("details").hidden = true;
  $("nova-analise").scrollIntoView({ behavior: "smooth" }); jobInput.focus();
});

function readHistory() {
  try { const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); return Array.isArray(value) ? value : []; }
  catch { return []; }
}
function writeHistory(items) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 10))); return true; }
  catch { message("render-error", "Não foi possível salvar neste navegador. Verifique o espaço disponível."); return false; }
}
function historyButton(label, onClick) {
  const button = document.createElement("button"); button.type = "button"; button.className = "outline-button"; button.textContent = label; button.addEventListener("click", onClick); return button;
}
function showHistory() {
  const list = $("history-list"); list.replaceChildren();
  const items = readHistory();
  if (!items.length) { const empty = document.createElement("p"); empty.className = "history-empty"; empty.textContent = "Nenhuma versão salva ainda. Após uma análise, use “Salvar versão”."; list.append(empty); return; }
  for (const entry of items) {
    const card = document.createElement("article"); card.className = "history-card";
    const choice = document.createElement("input"); choice.type = "checkbox"; choice.value = entry.id; choice.className = "compare-check"; choice.setAttribute("aria-label", `Selecionar ${entry.label} para comparar`);
    const info = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = entry.label;
    const sub = document.createElement("span"); sub.textContent = `${new Date(entry.date).toLocaleString("pt-BR")} · ${entry.percentage}% de alinhamento`;
    info.append(title, sub);
    const actions = document.createElement("div"); actions.className = "history-actions";
    actions.append(historyButton("Abrir", async () => {
      jobInput.value = entry.jobDescription || entry.label;
      $("job-count").textContent = `${jobInput.value.length.toLocaleString("pt-BR")} / 20.000`;
      showAnalysis(entry.analysis);
      await refreshPreview();
    }));
    actions.append(historyButton("Excluir", async () => {
      try {
        await AlinhaStorage.deleteVersion(entry.id);
        writeHistory(readHistory().filter((item) => item.id !== entry.id));
        showHistory(); $("comparison").hidden = true; updateJobsProfile();
      } catch (error) { message("render-error", error.message); }
    }));
    card.append(choice, info, actions); list.append(card);
  }
  list.append(historyButton("Comparar duas selecionadas", compareHistory));
}
function compareHistory() {
  const ids = [...document.querySelectorAll(".compare-check:checked")].map((item) => item.value);
  const panel = $("comparison"); panel.replaceChildren();
  if (ids.length !== 2) { const text = document.createElement("p"); text.textContent = "Selecione exatamente duas versões para comparar."; panel.append(text); panel.hidden = false; return; }
  const entries = ids.map((id) => readHistory().find((item) => item.id === id));
  for (const entry of entries) {
    const card = document.createElement("article"); card.className = "detail-card";
    const heading = document.createElement("h3"); heading.textContent = entry.label;
    const score = document.createElement("strong"); score.textContent = `${entry.percentage}% de alinhamento`;
    const summary = document.createElement("p"); summary.textContent = entry.analysis.draft.summary || "Sem resumo.";
    const gaps = document.createElement("p"); gaps.textContent = `Lacunas: ${entry.analysis.gaps.join("; ") || "nenhuma identificada"}`;
    card.append(heading, score, summary, gaps); panel.append(card);
  }
  panel.hidden = false; panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
$("save-version").addEventListener("click", async () => {
  if (!analysis) return;
  if (lastRenderedDraft !== JSON.stringify(currentDraft()) && !await refreshPreview()) return;
  const label = jobInput.value.trim().slice(0, 65) || analysis.draft.headline || "Análise sem título";
  const entry = { id: crypto.randomUUID(), date: new Date().toISOString(), label, jobDescription: jobInput.value, percentage: analysis.percentage, analysis: JSON.parse(JSON.stringify(analysis)) };
  const button = $("save-version");
  button.disabled = true;
  try {
    await AlinhaStorage.saveVersion(entry);
    if (writeHistory([entry, ...readHistory()])) {
      showHistory(); updateJobsProfile(); button.textContent = "Versão salva ✓";
      setTimeout(() => { button.textContent = "Salvar versão"; }, 2200);
    }
  } catch (error) { message("render-error", error.message); }
  finally { button.disabled = false; }
});
$("copy-latex").disabled = true;
$("download-latex").disabled = true;
document.querySelector(".latex-heading p").textContent = "Código gerado a partir dos campos editáveis acima.";
document.querySelector(".guide-steps>div:last-child p").textContent = "Edite, visualize e baixe o currículo em PDF ou LaTeX.";
showHistory();
updateJobsProfile();
function restorePendingRoadmapKeywords() {
  const pending = AlinhaRoadmapKeywords.readPending();
  if (!pending) return;
  const working = AlinhaRoadmapKeywords.readWorking();
  const latest = readHistory()[0];
  for (const candidate of [working, latest && { analysis: latest.analysis, jobDescription: latest.jobDescription }]) {
    if (!candidate?.analysis?.draft) continue;
    try {
      jobInput.value = candidate.jobDescription || "";
      $("job-count").textContent = `${jobInput.value.length.toLocaleString("pt-BR")} / 20.000`;
      showAnalysis(candidate.analysis, false);
      return;
    } catch { /* Try the next available version. */ }
  }
  $('roadmap-keywords-notice').textContent = `As palavras-chave da rota ${pending.title} estão prontas. Envie seu currículo e faça uma análise para adicioná-las ao campo Habilidades.`;
  $('roadmap-keywords-notice').hidden = false;
}
AlinhaStorage.readyVersions().then((versions) => {
  if (versions === null) { restorePendingRoadmapKeywords(); return; }
  showHistory(); updateJobsProfile();
  $("save-version").textContent = "Salvar versão";
  document.querySelector("#history-section .section-kicker").textContent = "SALVO NO SERVIDOR";
  document.querySelector("#history-section .section-heading p").textContent = "Recupere versões anteriores ou compare duas análises. Os dados ficam no PostgreSQL deste servidor.";
  document.querySelector(".editor-card .privacy-note").textContent = "A IA usa informações com evidência. Revise o texto antes de se candidatar; filtros ATS não garantem aprovação. As versões salvas ficam no PostgreSQL deste servidor. Para acessá-las em outros dispositivos, crie uma conta.";
  restorePendingRoadmapKeywords();
}).catch((error) => {
  document.querySelector("#history-section .section-heading p").textContent = `Não foi possível sincronizar o PostgreSQL: ${error.message}. As versões anteriores continuam neste navegador.`;
  restorePendingRoadmapKeywords();
});
function jobsDraft() {
  if (analysis && $("draft-name")) return currentDraft();
  return readHistory()[0]?.analysis?.draft || null;
}
function updateJobsProfile() {
  $("jobs-profile").textContent = analysis
    ? "Busca baseada nos campos editáveis da versão atual."
    : readHistory().length
      ? "Busca baseada na última versão salva."
      : "Abra uma versão salva ou faça uma análise para buscar vagas.";
}
function makeJobCard(job) {
  const card = document.createElement("article");
  card.className = "job-card";
  const top = document.createElement("div"); top.className = "job-card-top";
  const source = document.createElement("span"); source.className = "job-source"; source.textContent = job.source;
  const match = document.createElement("span"); match.className = "job-match";
  match.textContent = job.matched_terms?.length ? `${job.matched_terms.length} termos em comum` : "Cargo relacionado";
  top.append(source, match);
  const title = document.createElement("h3"); title.textContent = job.title;
  const meta = document.createElement("p"); meta.className = "job-meta";
  meta.textContent = `${job.company} · ${job.location}${job.remote ? " · Remota" : ""}`;
  const description = document.createElement("p"); description.className = "job-description";
  description.textContent = job.description || "Veja os detalhes e requisitos na plataforma de origem.";
  const tags = document.createElement("div"); tags.className = "job-tags";
  for (const term of job.matched_terms || []) {
    const tag = document.createElement("span"); tag.textContent = term; tags.append(tag);
  }
  const link = document.createElement("a");
  link.textContent = `Ver vaga em ${job.source} ↗`;
  link.target = "_blank"; link.rel = "noopener noreferrer";
  try { const url = new URL(job.url); if (url.protocol === "https:") link.href = url.href; }
  catch { /* Ignore invalid links from providers. */ }
  card.append(top, title, meta, description, tags);
  if (link.href) card.append(link);
  const register = document.createElement("button");
  register.type = "button";
  register.className = "outline-button job-register-button";
  register.textContent = "Registrar candidatura →";
  register.addEventListener("click", () => {
    try {
      sessionStorage.setItem("alinha-application-prefill-v1", JSON.stringify({
        role: String(job.title || "").slice(0, 160),
        company: String(job.company || "").slice(0, 160),
        source: String(job.source || "").slice(0, 120),
        vacancyUrl: link.href || "",
        jobDescription: String(job.description || "").slice(0, 20000),
      }));
    } catch { /* The form remains available for manual entry. */ }
    location.href = "/candidaturas";
  });
  card.append(register);
  return card;
}
$("jobs-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const draft = jobsDraft();
  const status = $("jobs-status");
  const notices = $("jobs-notices");
  if (!draft) { status.textContent = "Faça uma análise ou abra uma versão salva para buscar vagas."; return; }
  const button = $("jobs-submit");
  button.disabled = true; button.textContent = "Buscando vagas...";
  status.textContent = "Consultando plataformas de vagas...";
  notices.textContent = "";
  $("jobs-list").replaceChildren();
  try {
    const result = await requestJson("/api/jobs/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        draft, query: $("jobs-query").value.trim(),
        location: $("jobs-location").value.trim(), work_mode: $("jobs-mode").value,
      }),
    });
    status.textContent = result.jobs.length
      ? `${result.jobs.length} vagas encontradas para “${result.query_used}”. Ordenadas por cargo e termos em comum com o currículo.`
      : `Nenhuma vaga alinhada encontrada para “${result.query_used}”. Tente outra palavra-chave ou modalidade.`;
    notices.textContent = result.notices.join(" ");
    if (result.jobs.length) for (const job of result.jobs) $("jobs-list").append(makeJobCard(job));
    else { const empty = document.createElement("p"); empty.className = "jobs-empty"; empty.textContent = "Experimente buscar por uma habilidade específica do currículo."; $("jobs-list").append(empty); }
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; button.textContent = "Buscar vagas alinhadas"; }
});
$("jobs-linkedin").addEventListener("click", () => {
  const draft = jobsDraft();
  const query = $("jobs-query").value.trim()
    || draft?.skills?.split("\n").map((value) => value.trim()).find((value) => value.length >= 3 && value.length <= 35)
    || draft?.headline?.split("|")[0].trim()
    || "";
  if (!query) { $("jobs-status").textContent = "Informe uma palavra-chave para buscar no LinkedIn."; return; }
  const url = new URL("https://www.linkedin.com/jobs/search/");
  url.searchParams.set("keywords", query);
  url.searchParams.set("location", $("jobs-location").value.trim() || "Brasil");
  window.open(url.toString(), "_blank", "noopener,noreferrer");
});
fetch("/api/config").then((response) => response.json()).then((config) => {
  if (config.auth_required) {
    $("access-field").hidden = false;
    $("access-token").value = sessionStorage.getItem("alinha-access-token") || "";
  }
}).catch(() => {});
$("access-token").addEventListener("input", () => {
  sessionStorage.setItem("alinha-access-token", $("access-token").value);
});
function updateNavigation() {
  const hash = ["#vagas", "#como-funciona"].includes(location.hash) ? location.hash : "#nova-analise";
  for (const link of document.querySelectorAll(".side-nav .nav-link")) {
    const active = link.getAttribute("href") === hash;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.querySelector(".topbar-title span").textContent = hash === "#vagas"
    ? "/ Vagas para você" : hash === "#como-funciona" ? "/ Como funciona" : "/ Nova análise";
}
window.addEventListener("hashchange", updateNavigation);
updateNavigation();
if (location.hash === "#rotas-estudo") location.replace("/rotas-estudo");
for (const link of document.querySelectorAll('a[href="/rotas-estudo"]')) {
  link.addEventListener("click", () => {
    if (!analysis || !$('draft-skills')) return;
    try { AlinhaRoadmapKeywords.saveWorking({ analysis: { ...analysis, draft: currentDraft() }, jobDescription: jobInput.value }); }
    catch { /* The last saved version remains available if session storage is full. */ }
  });
}
for (const link of document.querySelectorAll('a[href="/certificacoes"]')) {
  link.addEventListener("click", () => {
    if (!analysis || !$("draft-skills")) return;
    const draft = currentDraft();
    const profile = [draft.headline, draft.skills, draft.summary, draft.projects].filter(Boolean).join("\n").slice(0, 12_000);
    try { sessionStorage.setItem("alinha-cert-profile-v1", profile); }
    catch { /* O usuário ainda pode enviar o currículo na página de certificações. */ }
  });
}
