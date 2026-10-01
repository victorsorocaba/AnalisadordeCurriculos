const CERT_PROFILE_KEY = "alinha-cert-profile-v1";
const CERT_HISTORY_KEY = "alinha-versions-v1";
const MAX_CERT_FILE_BYTES = 10 * 1024 * 1024;
const certElement = (id) => document.getElementById(id);
const certForm = certElement("certification-form");
const certFile = certElement("certification-resume");
const certGoal = certElement("certification-goal");
const certStatus = certElement("certification-status");
const certList = certElement("certification-list");
const certError = certElement("certification-error");
const certButton = certElement("certification-submit");

function profileFromDraft(draft) {
  if (!draft || typeof draft !== "object") return "";
  return ["headline", "skills", "summary", "projects"]
    .map((key) => typeof draft[key] === "string" ? draft[key] : "")
    .filter(Boolean).join("\n").slice(0, 12_000);
}

function loadCertificationProfile() {
  try {
    const active = sessionStorage.getItem(CERT_PROFILE_KEY);
    if (active) return { text: active.slice(0, 12_000), source: "Habilidades da análise atual" };
  } catch { /* Continue with a saved version. */ }
  try {
    const history = JSON.parse(localStorage.getItem(CERT_HISTORY_KEY) || "[]");
    const draft = Array.isArray(history) ? history[0]?.analysis?.draft : null;
    const text = profileFromDraft(draft);
    if (text) return { text, source: "Habilidades da última versão salva" };
  } catch { /* The user can upload a file or enter a goal. */ }
  return { text: "", source: "Nenhum currículo disponível nesta sessão. Envie um arquivo ou informe seu objetivo." };
}

const currentCertificationProfile = loadCertificationProfile();
certElement("certification-profile-source").textContent = currentCertificationProfile.source;

function certificationCard(item) {
  const card = document.createElement("article");
  card.className = "certification-card";
  const top = document.createElement("div");
  top.className = "certification-card-top";
  const provider = document.createElement("span");
  provider.className = "certification-provider";
  provider.textContent = item.provider;
  const level = document.createElement("span");
  level.className = "certification-level";
  level.textContent = item.level;
  top.append(provider, level);
  const heading = document.createElement("h3");
  heading.textContent = item.title;
  const area = document.createElement("p");
  area.className = "certification-area";
  area.textContent = item.area;
  const reason = document.createElement("p");
  reason.className = "certification-reason";
  reason.textContent = item.reason;
  const terms = document.createElement("div");
  terms.className = "job-tags";
  for (const term of item.matched_terms || []) {
    const tag = document.createElement("span");
    tag.textContent = term;
    terms.append(tag);
  }
  const link = document.createElement("a");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Ver certificação oficial ↗";
  card.append(top, heading, area, reason, terms, link);
  return card;
}

async function findCertifications(event) {
  event?.preventDefault();
  certError.hidden = true;
  certError.textContent = "";
  const file = certFile.files[0];
  const goal = certGoal.value.trim();
  if (!file && !currentCertificationProfile.text && !goal) {
    certError.textContent = "Envie um currículo ou informe o cargo ou área que você deseja alcançar.";
    certError.hidden = false;
    return;
  }
  if (file) {
    const extension = file.name.split(".").pop().toLowerCase();
    if (!["pdf", "txt"].includes(extension) || file.size === 0 || file.size > MAX_CERT_FILE_BYTES) {
      certError.textContent = "Escolha um PDF ou TXT não vazio com até 10 MB.";
      certError.hidden = false;
      return;
    }
  }
  certButton.disabled = true;
  certButton.textContent = "Analisando seu perfil...";
  certStatus.textContent = "Identificando certificações relacionadas...";
  certList.replaceChildren();
  const body = new FormData();
  body.set("profile_text", currentCertificationProfile.text);
  body.set("goal", goal);
  if (file) body.set("resume", file);
  const headers = {};
  try {
    const token = sessionStorage.getItem("alinha-access-token");
    if (token) headers["X-Access-Token"] = token;
  } catch { /* The server may not require a token. */ }
  try {
    const response = await fetch("/api/certifications/recommend", { method: "POST", headers, body });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Não foi possível analisar o perfil.");
    if (!result.recommendations.length) {
      certStatus.textContent = "Não encontramos uma correspondência segura no catálogo. Informe uma área ou habilidade mais específica.";
      return;
    }
    certStatus.textContent = `${result.recommendations.length} sugestões com base em ${result.source.toLowerCase()}. Catálogo com ${result.catalog_size} certificações oficiais.`;
    certList.replaceChildren(...result.recommendations.map(certificationCard));
  } catch (error) {
    certStatus.textContent = "Não foi possível carregar as sugestões.";
    certError.textContent = error.message;
    certError.hidden = false;
  } finally {
    certButton.disabled = false;
    certButton.textContent = "Encontrar certificações";
  }
}

certForm.addEventListener("submit", findCertifications);
if (currentCertificationProfile.text) findCertifications();
