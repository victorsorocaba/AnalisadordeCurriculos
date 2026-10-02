const applicationElements = {
  form: document.getElementById("application-form"),
  role: document.getElementById("application-role"),
  company: document.getElementById("application-company"),
  date: document.getElementById("application-date"),
  source: document.getElementById("application-source"),
  url: document.getElementById("application-url"),
  notes: document.getElementById("application-notes"),
  response: document.getElementById("application-response"),
  submit: document.getElementById("application-submit"),
  cancel: document.getElementById("application-cancel"),
  formTitle: document.getElementById("application-form-title"),
  formMessage: document.getElementById("application-form-message"),
  month: document.getElementById("applications-month"),
  allMonths: document.getElementById("applications-all-months"),
  filterDescription: document.getElementById("applications-filter-description"),
  total: document.getElementById("applications-total"),
  periodTotal: document.getElementById("applications-period-total"),
  periodLabel: document.getElementById("applications-period-label"),
  responses: document.getElementById("applications-responses"),
  responseRate: document.getElementById("applications-response-rate"),
  activeDays: document.getElementById("applications-active-days"),
  daily: document.getElementById("applications-daily"),
  monthly: document.getElementById("applications-monthly"),
  summary: document.getElementById("applications-list-summary"),
  error: document.getElementById("applications-error"),
  list: document.getElementById("applications-list"),
};
let applications = [];
let editingId = null;
const currentDate = new Date();
const today = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, "0")}-${String(currentDate.getDate()).padStart(2, "0")}`;
applicationElements.date.max = today;
applicationElements.date.value = today;
applicationElements.month.value = today.slice(0, 7);
try {
  const prefill = JSON.parse(sessionStorage.getItem("alinha-application-prefill-v1") || "null");
  if (prefill && typeof prefill === "object") {
    applicationElements.role.value = String(prefill.role || "").slice(0, 160);
    applicationElements.company.value = String(prefill.company || "").slice(0, 160);
    applicationElements.source.value = String(prefill.source || "").slice(0, 120);
    applicationElements.url.value = String(prefill.vacancyUrl || "").slice(0, 2000);
    applicationElements.formMessage.textContent = "Confira os dados da vaga e salve após enviar sua candidatura.";
  }
  sessionStorage.removeItem("alinha-application-prefill-v1");
} catch { /* Manual entry is still available. */ }

function dateLabel(value) {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00`));
}

function monthLabel(value) {
  return new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(new Date(`${value}-01T12:00:00`));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showError(text) {
  applicationElements.error.textContent = text;
  applicationElements.error.hidden = !text;
}

function resetForm() {
  editingId = null;
  applicationElements.form.reset();
  applicationElements.date.value = today;
  applicationElements.formTitle.textContent = "Nova candidatura";
  applicationElements.submit.textContent = "Salvar candidatura";
  applicationElements.cancel.hidden = true;
}

function editApplication(application) {
  editingId = application.id;
  applicationElements.role.value = application.role;
  applicationElements.company.value = application.company;
  applicationElements.date.value = application.appliedOn;
  applicationElements.source.value = application.source;
  applicationElements.url.value = application.vacancyUrl || "";
  applicationElements.notes.value = application.notes || "";
  applicationElements.response.checked = Boolean(application.responseReceived);
  applicationElements.formTitle.textContent = "Editar candidatura";
  applicationElements.submit.textContent = "Salvar alterações";
  applicationElements.cancel.hidden = false;
  applicationElements.formMessage.textContent = "Edite os dados e salve para atualizar o histórico.";
  applicationElements.form.scrollIntoView({ behavior: "smooth", block: "start" });
  applicationElements.role.focus();
}

function applicationCard(application) {
  const card = element("article", "application-card");
  const info = element("div", "application-card-info");
  const top = element("div", "application-card-top");
  top.append(element("h3", "", application.role), element("span", "application-company", application.company));
  const meta = element("p", "application-card-meta", `${dateLabel(application.appliedOn)} · ${application.source}`);
  info.append(top, meta);
  if (application.vacancyUrl) {
    try {
      const url = new URL(application.vacancyUrl);
      if (["http:", "https:"].includes(url.protocol)) {
      const link = element("a", "application-vacancy-link", "Abrir anúncio ↗");
      link.href = url.toString();
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      info.append(link);
      }
    } catch {
      // Older local data may contain an invalid URL. Keep the application visible.
    }
  }
  if (application.notes) info.append(element("p", "application-notes", application.notes));
  const actions = element("div", "application-card-actions");
  const responseLabel = element("label", "application-response-control");
  const response = document.createElement("input");
  response.type = "checkbox";
  response.checked = Boolean(application.responseReceived);
  response.setAttribute("aria-label", `Teve retorno da candidatura para ${application.role} na ${application.company}`);
  response.addEventListener("change", async () => {
    response.disabled = true;
    showError("");
    try {
      const { id, ...body } = application;
      await AlinhaStorage.updateApplication(id, { ...body, responseReceived: response.checked });
      renderApplications();
    } catch (error) {
      response.checked = !response.checked;
      showError(`Não foi possível atualizar o retorno: ${error.message}`);
      response.disabled = false;
    }
  });
  responseLabel.append(response, element("span", "", "Teve retorno"));
  const edit = element("button", "outline-button", "Editar");
  edit.type = "button";
  edit.addEventListener("click", () => editApplication(application));
  const remove = element("button", "application-delete", "Excluir");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    if (!window.confirm(`Excluir a candidatura para ${application.role} na ${application.company}?`)) return;
    remove.disabled = true;
    showError("");
    try {
      await AlinhaStorage.deleteApplication(application.id);
      if (editingId === application.id) resetForm();
      renderApplications();
    } catch (error) {
      showError(`Não foi possível excluir: ${error.message}`);
      remove.disabled = false;
    }
  });
  actions.append(responseLabel, edit, remove);
  card.append(info, actions);
  return card;
}

function renderApplications() {
  const month = applicationElements.month.value;
  const metrics = AlinhaApplicationMetrics.summarize(applications, month);
  applicationElements.total.textContent = metrics.total.toLocaleString("pt-BR");
  applicationElements.periodTotal.textContent = metrics.periodTotal.toLocaleString("pt-BR");
  applicationElements.periodLabel.textContent = month ? monthLabel(month) : "em todo o histórico";
  applicationElements.responses.textContent = metrics.responses.toLocaleString("pt-BR");
  applicationElements.responseRate.textContent = `${metrics.responseRate}% do período`;
  applicationElements.activeDays.textContent = metrics.activeDays.toLocaleString("pt-BR");
  applicationElements.filterDescription.textContent = month ? `Exibindo ${monthLabel(month)}` : "Exibindo todo o histórico";
  applicationElements.summary.textContent = `${metrics.periodTotal} ${metrics.periodTotal === 1 ? "candidatura registrada" : "candidaturas registradas"}${month ? ` em ${monthLabel(month)}` : " no total"}.`;

  const maxDaily = Math.max(1, ...metrics.daily.map((item) => item.count));
  const daily = metrics.daily.map((item) => {
    const row = element("div", "application-day-row");
    row.append(element("span", "application-day-label", dateLabel(item.date)));
    const track = element("div", "application-day-track");
    const bar = element("span", "application-day-bar");
    bar.style.width = `${Math.max(6, item.count / maxDaily * 100)}%`;
    track.append(bar);
    row.append(track, element("strong", "", String(item.count)));
    return row;
  });
  applicationElements.daily.replaceChildren(...(daily.length ? daily : [element("p", "applications-empty", "Nenhuma candidatura neste período.")]));

  const monthly = metrics.monthly.map((item) => {
    const button = element("button", "application-month-button");
    button.type = "button";
    button.classList.toggle("is-selected", item.month === month);
    button.append(element("span", "", monthLabel(item.month)), element("strong", "", `${item.count} ${item.count === 1 ? "vaga" : "vagas"}`));
    button.addEventListener("click", () => { applicationElements.month.value = item.month; renderApplications(); });
    return button;
  });
  applicationElements.monthly.replaceChildren(...(monthly.length ? monthly : [element("p", "applications-empty", "Os meses com candidaturas aparecerão aqui.")]));

  const records = metrics.period.slice().sort((a, b) => b.appliedOn.localeCompare(a.appliedOn));
  applicationElements.list.replaceChildren(...(records.length ? records.map(applicationCard) : [element("p", "applications-empty", "Nenhuma vaga registrada neste período. Use o formulário para começar ou selecione outro mês.")]));
}

applicationElements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  applicationElements.formMessage.textContent = "";
  showError("");
  if (!applicationElements.form.reportValidity()) return;
  const vacancyUrl = applicationElements.url.value.trim();
  if (vacancyUrl && !["http:", "https:"].includes(new URL(vacancyUrl).protocol)) {
    applicationElements.formMessage.textContent = "O link da vaga deve começar com http:// ou https://.";
    return;
  }
  if (applicationElements.date.value > today) {
    applicationElements.formMessage.textContent = "A data da candidatura não pode estar no futuro.";
    return;
  }
  const application = {
    role: applicationElements.role.value.trim(), company: applicationElements.company.value.trim(),
    appliedOn: applicationElements.date.value, source: applicationElements.source.value.trim(),
    vacancyUrl: vacancyUrl || null, notes: applicationElements.notes.value.trim(),
    responseReceived: applicationElements.response.checked,
  };
  if (!application.role || !application.company || !application.source) {
    applicationElements.formMessage.textContent = "Informe cargo, empresa e onde encontrou a vaga.";
    return;
  }
  applicationElements.submit.disabled = true;
  try {
    if (editingId) await AlinhaStorage.updateApplication(editingId, application);
    else await AlinhaStorage.saveApplication(application);
    applicationElements.month.value = application.appliedOn.slice(0, 7);
    resetForm();
    renderApplications();
    applicationElements.formMessage.textContent = "Candidatura salva no histórico.";
  } catch (error) {
    applicationElements.formMessage.textContent = `Não foi possível salvar: ${error.message}`;
  } finally { applicationElements.submit.disabled = false; }
});
applicationElements.cancel.addEventListener("click", () => { resetForm(); applicationElements.formMessage.textContent = ""; });
applicationElements.month.addEventListener("change", renderApplications);
applicationElements.allMonths.addEventListener("click", () => { applicationElements.month.value = ""; renderApplications(); });

AlinhaStorage.readyApplications().then((entries) => {
  applications = entries;
  renderApplications();
}).catch((error) => {
  applicationElements.summary.textContent = "Não foi possível carregar o histórico.";
  showError(error.message);
});
