const accountForm = document.getElementById("account-form");
const accountMessage = document.getElementById("account-message");
const accountCurrent = document.getElementById("account-current");
const accountLogout = document.getElementById("account-logout");
const accountToggle = document.getElementById("account-toggle");
let loginMode = false;

async function accountRequest(path, body) {
  const response = await fetch(`/api/account/${path}`, {
    method: "POST", headers: {
      "Content-Type": "application/json", "X-Profile-Key": AlinhaStorage.profileKey(),
      ...(AlinhaStorage.sessionToken() ? { "X-Session-Token": AlinhaStorage.sessionToken() } : {}),
    }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Não foi possível acessar a conta.");
  }
  return response.json();
}

function renderMode() {
  document.getElementById("account-title").textContent = loginMode ? "Entrar na conta" : "Criar conta";
  document.getElementById("account-submit").textContent = loginMode ? "Entrar" : "Criar conta";
  accountToggle.textContent = loginMode ? "Criar uma conta" : "Já tenho conta";
  document.getElementById("account-password").autocomplete = loginMode ? "current-password" : "new-password";
}

accountToggle.addEventListener("click", () => { loginMode = !loginMode; accountMessage.textContent = ""; renderMode(); });
accountForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!accountForm.reportValidity()) return;
  const submit = document.getElementById("account-submit");
  submit.disabled = true;
  accountMessage.textContent = loginMode ? "Entrando..." : "Salvando seu perfil...";
  try {
    if (!loginMode) {
      await Promise.all([AlinhaStorage.readyVersions(), AlinhaStorage.readyRoadmaps(), AlinhaStorage.readyTopics(), AlinhaStorage.readyApplications()]);
    }
    const result = await accountRequest(loginMode ? "login" : "register", {
      email: document.getElementById("account-email").value.trim(),
      password: document.getElementById("account-password").value,
    });
    AlinhaStorage.setSession(result.sessionToken);
    location.href = "/";
  } catch (error) {
    accountMessage.textContent = error.message;
    submit.disabled = false;
  }
});

accountLogout.addEventListener("click", async () => {
  accountLogout.disabled = true;
  try {
    await fetch("/api/account/logout", { method: "POST", headers: { "X-Session-Token": AlinhaStorage.sessionToken() } });
  } finally {
    AlinhaStorage.setSession("");
    location.reload();
  }
});

(async () => {
  try {
    const status = await fetch("/api/storage/status").then((response) => response.json());
    if (!status.enabled) {
      accountCurrent.textContent = "PostgreSQL indisponível. Ative o banco para criar ou acessar uma conta.";
      document.getElementById("account-submit").disabled = true;
      return;
    }
    if (!AlinhaStorage.sessionToken()) { accountCurrent.textContent = "Perfil local deste navegador."; return; }
    const response = await fetch("/api/account/me", { headers: { "X-Session-Token": AlinhaStorage.sessionToken() } });
    if (!response.ok) throw new Error("Sessão expirada.");
    const data = await response.json();
    accountCurrent.textContent = `Conectado como ${data.email}`;
    accountLogout.hidden = false;
  } catch (error) { accountCurrent.textContent = error.message; accountLogout.hidden = false; }
})();
