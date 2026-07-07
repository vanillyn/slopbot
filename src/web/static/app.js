const state = {
  guilds: [],
  selectedGuild: null,
  token: null,
};

const elements = {
  loginButton: document.getElementById("login-button"),
  logoutButton: document.getElementById("logout-button"),
  guildList: document.getElementById("guild-list"),
  dashboardRoot: document.getElementById("dashboard-root"),
  configPanel: document.getElementById("config-panel"),
  actionsPanel: document.getElementById("actions-panel"),
  backButton: document.getElementById("back-button"),
  actionsBack: document.getElementById("actions-back"),
  saveConfig: document.getElementById("save-config"),
  actionPanel: document.getElementById("action-panel"),
  selectedGuildTitle: document.getElementById("selected-guild-title"),
  guildName: document.getElementById("guild-name"),
  moderatorRole: document.getElementById("moderator-role"),
  adminRole: document.getElementById("admin-role"),
  memberRole: document.getElementById("member-role"),
  imageRole: document.getElementById("image-role"),
  musicRole: document.getElementById("music-role"),
  ticketChannel: document.getElementById("ticket-channel"),
  ticketMessage: document.getElementById("ticket-message"),
  ticketPanelsButton: document.getElementById("ticket-panels-button"),
  containersButton: document.getElementById("containers-button"),
  ticketPanelBack: document.getElementById("ticket-panel-back"),
  ticketPanelChannel: document.getElementById("ticket-panel-channel"),
  ticketPanelCategory: document.getElementById("ticket-panel-category"),
  ticketPanelStaffRole: document.getElementById("ticket-panel-staff-role"),
  ticketPanelTitle: document.getElementById("ticket-panel-title"),
  ticketPanelDescription: document.getElementById("ticket-panel-description"),
  ticketPanelsList: document.getElementById("ticket-panels-list"),
  createTicketPanel: document.getElementById("create-ticket-panel"),
  containersPanel: document.getElementById("containers-panel"),
  containersBack: document.getElementById("containers-back"),
  containerName: document.getElementById("container-name"),
  containerAccent: document.getElementById("container-accent"),
  containerItems: document.getElementById("container-items"),
  containerList: document.getElementById("container-list"),
  saveContainer: document.getElementById("save-container"),
};

function authHeaders() {
  return {
    Authorization: `Bearer ${state.token}`,
    "Content-Type": "application/json",
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  return response.json();
}

function setPanelVisible(panel, visible) {
  panel.hidden = !visible;
}

function hideAllPanels() {
  setPanelVisible(elements.dashboardRoot, false);
  setPanelVisible(elements.configPanel, false);
  setPanelVisible(elements.actionsPanel, false);
  setPanelVisible(elements.ticketPanel, false);
  setPanelVisible(elements.containersPanel, false);
}

function buildGuildCard(guild) {
  const card = document.createElement("button");
  card.className = "button button-secondary";
  card.textContent = guild.name;
  card.addEventListener("click", () => selectGuild(guild));
  return card;
}

function resetPanels() {
  hideAllPanels();
}

function fillSelect(select, items, selectedValue) {
  select.innerHTML = "<option value=''>none</option>";
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    if (item.id === selectedValue) option.selected = true;
    select.appendChild(option);
  });
}

async function loadGuilds() {
  const result = await fetchJson("/api/guilds", { headers: authHeaders() });
  if (result.error) {
    alert(result.error);
    return;
  }
  state.guilds = result;
  elements.guildList.innerHTML = "";
  result.forEach((guild) => {
    elements.guildList.appendChild(buildGuildCard(guild));
  });
  elements.guildName.textContent = "select a server";
  setPanelVisible(elements.dashboardRoot, true);
}

async function selectGuild(guild) {
  state.selectedGuild = guild;
  elements.selectedGuildTitle.textContent = `${guild.name} settings`;
  elements.guildName.textContent = guild.name;
  await loadRolesAndChannels(guild.id);
  resetPanels();
  setPanelVisible(elements.configPanel, true);
}

async function loadRolesAndChannels(guildId) {
  const [roles, channels, config] = await Promise.all([
    fetchJson(`/api/guild/${guildId}/roles`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/channels`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/config`, { headers: authHeaders() }),
  ]);

  function fillSelect(select, items, selectedValue) {
    select.innerHTML = "<option value=''>none</option>";
    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      if (item.id === selectedValue) option.selected = true;
      select.appendChild(option);
    });
  }

  fillSelect(elements.moderatorRole, roles, config.moderator_role || "");
  fillSelect(elements.adminRole, roles, config.admin_role || "");
  fillSelect(elements.memberRole, roles, config.member_role || "");
  fillSelect(elements.imageRole, roles, config.image_role || "");
  fillSelect(elements.musicRole, roles, config.music_role || "");
  fillSelect(elements.ticketChannel, channels.filter((channel) => channel.type === "text"), config.ticket_channel || "");
  fillSelect(elements.ticketPanelChannel, channels.filter((channel) => channel.type === "text"), "");
  const categoryOptions = channels.filter((channel) => channel.type === "category");
  fillSelect(elements.ticketPanelCategory, categoryOptions, "");
  fillSelect(elements.ticketPanelStaffRole, roles, "");
  elements.ticketMessage.value = config.ticket_message || "create a ticket for help";
}

async function saveConfig() {
  if (!state.selectedGuild) return;
  const payload = {
    moderator_role: elements.moderatorRole.value || null,
    admin_role: elements.adminRole.value || null,
    member_role: elements.memberRole.value || null,
    image_role: elements.imageRole.value || null,
    music_role: elements.musicRole.value || null,
    ticket_channel: elements.ticketChannel.value || null,
    ticket_message: elements.ticketMessage.value || null,
  };
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/config`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    alert("settings saved");
  } else {
    alert(result.error || "failed to save settings");
  }
}

function showActionsPanel() {
  resetPanels();
  setPanelVisible(elements.actionsPanel, true);
}

function showPanel(panel) {
  resetPanels();
  setPanelVisible(panel, true);
}

function renderList(container, items, renderItem) {
  container.innerHTML = "";
  items.forEach((item) => {
    const element = renderItem(item);
    container.appendChild(element);
  });
}

async function loadTicketPanels() {
  if (!state.selectedGuild) return;
  const panels = await fetchJson(`/api/guild/${state.selectedGuild.id}/ticket_panels`, { headers: authHeaders() });
  if (panels.error) {
    alert(panels.error);
    return;
  }
  renderList(elements.ticketPanelsList, panels, (panel) => {
    const card = document.createElement("div");
    card.className = "panel-card";
    card.innerHTML = `<strong>${panel.title}</strong><div>${panel.description}</div><div>channel: ${panel.channel_id}</div>`;
    return card;
  });
}

async function createTicketPanel() {
  if (!state.selectedGuild) return;
  const payload = {
    channel_id: elements.ticketPanelChannel.value || null,
    category_id: elements.ticketPanelCategory.value || null,
    staff_role_id: elements.ticketPanelStaffRole.value || null,
    title: elements.ticketPanelTitle.value || "support",
    description: elements.ticketPanelDescription.value || "click below to open a ticket",
  };
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/ticket_panels`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    alert("ticket panel created");
    loadTicketPanels();
  } else {
    alert(result.error || "failed to create ticket panel");
  }
}

async function loadContainers() {
  if (!state.selectedGuild) return;
  const containers = await fetchJson(`/api/guild/${state.selectedGuild.id}/containers`, { headers: authHeaders() });
  if (containers.error) {
    alert(containers.error);
    return;
  }
  renderList(elements.containerList, containers, (container) => {
    const card = document.createElement("div");
    card.className = "panel-card";
    card.innerHTML = `<strong>${container.name}</strong><div>items: ${JSON.stringify(container.items)}</div><div>accent: ${container.accent_color ?? "none"}</div>`;
    return card;
  });
}

async function saveContainer() {
  if (!state.selectedGuild) return;
  let items;
  try {
    items = JSON.parse(elements.containerItems.value || "[]");
  } catch (error) {
    alert("container items must be valid JSON");
    return;
  }
  const payload = {
    name: elements.containerName.value.trim(),
    items,
    accent_color: elements.containerAccent.value ? Number(elements.containerAccent.value) : null,
  };
  if (!payload.name) {
    alert("container name is required");
    return;
  }
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/containers`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    alert("container saved");
    loadContainers();
  } else {
    alert(result.error || "failed to save container");
  }
}

function signOut() {
  state.token = null;
  resetPanels();
  elements.dashboardRoot.hidden = true;
  elements.loginButton.hidden = false;
}

async function executeAction(action) {
  if (!state.selectedGuild) return;
  const body = { url: "" };
  if (action === "play") {
    body.url = prompt("enter a YouTube URL to play:");
    if (!body.url) return;
  }
  if (action === "open_twitch") {
    body.url = prompt("enter a Twitch channel URL:");
    if (!body.url) return;
  }
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/actions/${action}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (result.ok) {
    alert(result.message || "action completed");
  } else {
    alert(result.error || "action failed");
  }
}

function showPanel(panel) {
  resetPanels();
  setPanelVisible(panel, true);
  if (panel === elements.ticketPanel) {
    loadTicketPanels();
  }
  if (panel === elements.containersPanel) {
    loadContainers();
  }
}

function initEvents() {
  elements.loginButton.addEventListener("click", () => {
    const clientId = "1523841754556530808";
    const redirect = encodeURIComponent(`${window.location.origin}/`);
    window.location.href = `https://discord.com/api/oauth2/authorize?client_id=${clientId}&redirect_uri=${redirect}&response_type=token&scope=identify%20guilds`;
  });

  elements.logoutButton.addEventListener("click", signOut);
  elements.backButton.addEventListener("click", () => showPanel(elements.configPanel));
  elements.actionsBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.saveConfig.addEventListener("click", saveConfig);
  elements.actionPanel.addEventListener("click", showActionsPanel);
  elements.ticketPanelsButton.addEventListener("click", () => showPanel(elements.ticketPanel));
  elements.containersButton.addEventListener("click", () => showPanel(elements.containersPanel));
  elements.ticketPanelBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.containersBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.createTicketPanel.addEventListener("click", createTicketPanel);
  elements.saveContainer.addEventListener("click", saveContainer);
  document.querySelectorAll(".tile-action").forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action));
  });
}

function parseToken() {
  const hash = window.location.hash.substring(1);
  const params = new URLSearchParams(hash);
  if (params.has("access_token")) {
    state.token = params.get("access_token");
    history.replaceState({}, document.title, window.location.pathname);
    elements.loginButton.hidden = true;
    loadGuilds();
  }
}

initEvents();
parseToken();
