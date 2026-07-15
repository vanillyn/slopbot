// API_BASE lets this page be hosted anywhere (GitHub Pages, Cloudflare Pages,
// same server as the bot, whatever) and still talk to the bot's dashboard
// API. Set window.COCO_API_BASE in index.html's inline <script> tag when the
// two aren't on the same origin. Empty string = same origin as this page.
const API_BASE = window.COCO_API_BASE || "";

const state = {
  guilds: [],
  selectedGuild: null,
  token: null,
  clientId: null,
};

const elements = {
  loginButton: document.getElementById("login-button"),
  logoutButton: document.getElementById("logout-button"),
  landingHero: document.getElementById("landing-hero"),
  guildList: document.getElementById("guild-list"),
  dashboardRoot: document.getElementById("dashboard-root"),
  configPanel: document.getElementById("config-panel"),
  actionsPanel: document.getElementById("actions-panel"),
  ticketPanel: document.getElementById("ticket-panel"),
  containersPanel: document.getElementById("containers-panel"),
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
  announcementChannel: document.getElementById("announcement-channel"),
  announcementRole: document.getElementById("announcement-role"),
  joinChannel: document.getElementById("join-channel"),
  joinMessages: document.getElementById("join-messages"),
  leaveChannel: document.getElementById("leave-channel"),
  leaveMessages: document.getElementById("leave-messages"),
  widgetEnabled: document.getElementById("widget-enabled"),
  widgetPreview: document.getElementById("widget-preview"),
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
  containerName: document.getElementById("container-name"),
  containerAccent: document.getElementById("container-accent"),
  containerItems: document.getElementById("container-items"),
  containerList: document.getElementById("container-list"),
  saveContainer: document.getElementById("save-container"),
  containersBack: document.getElementById("containers-back"),
  moderationButton: document.getElementById("moderation-button"),
  moderationPanel: document.getElementById("moderation-panel"),
  moderationBack: document.getElementById("moderation-back"),
  muteChannel: document.getElementById("mute-channel"),
  lockdownIncludeMemberRole: document.getElementById("lockdown-include-member-role"),
  requireConfirm: document.getElementById("require-confirm"),
  warnDm: document.getElementById("warn-dm"),
  warnChannel: document.getElementById("warn-channel"),
  kickDm: document.getElementById("kick-dm"),
  kickChannel: document.getElementById("kick-channel"),
  banDm: document.getElementById("ban-dm"),
  banChannel: document.getElementById("ban-channel"),
  muteDm: document.getElementById("mute-dm"),
  muteChannelMsg: document.getElementById("mute-channel-msg"),
  saveModeration: document.getElementById("save-moderation"),
};

function authHeaders() {
  return {
    Authorization: `Bearer ${state.token}`,
    "Content-Type": "application/json",
  };
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  return response.json();
}

function setPanelVisible(panel, visible) {
  if (panel) panel.hidden = !visible;
}

function hideAllPanels() {
  setPanelVisible(elements.dashboardRoot, false);
  setPanelVisible(elements.configPanel, false);
  setPanelVisible(elements.actionsPanel, false);
  setPanelVisible(elements.ticketPanel, false);
  setPanelVisible(elements.containersPanel, false);
  setPanelVisible(elements.moderationPanel, false);
}

function showPanel(panel) {
  hideAllPanels();
  setPanelVisible(panel, true);
  if (panel === elements.ticketPanel) loadTicketPanels();
  if (panel === elements.containersPanel) loadContainers();
  if (panel === elements.moderationPanel) loadModeration();
}

function buildGuildCard(guild) {
  const card = document.createElement("button");
  card.className = "button button-secondary";
  card.textContent = guild.name;
  card.addEventListener("click", () => selectGuild(guild));
  return card;
}

function fillSelect(select, items, selectedValue) {
  if (!select) return;
  select.innerHTML = "<option value=''>none</option>";
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    if (item.id === selectedValue) option.selected = true;
    select.appendChild(option);
  });
}

async function loadPublicConfig() {
  try {
    const config = await fetchJson("/api/config");
    state.clientId = config.discord_client_id || null;
  } catch (error) {
    console.error("could not load public config", error);
  }
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
  setPanelVisible(elements.landingHero, false);
  showPanel(elements.dashboardRoot);
}

async function selectGuild(guild) {
  state.selectedGuild = guild;
  elements.selectedGuildTitle.textContent = `${guild.name} settings`;
  elements.guildName.textContent = guild.name;
  await loadRolesAndChannels(guild.id);
  showPanel(elements.configPanel);
}

async function loadRolesAndChannels(guildId) {
  const [roles, channels, config] = await Promise.all([
    fetchJson(`/api/guild/${guildId}/roles`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/channels`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/config`, { headers: authHeaders() }),
  ]);

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

  const textChannels = channels.filter((channel) => channel.type === "text");
  fillSelect(elements.announcementChannel, textChannels, config.announcement_channel || "");
  fillSelect(elements.announcementRole, roles, config.announcement_role || "");
  fillSelect(elements.joinChannel, textChannels, config.join_channel || "");
  fillSelect(elements.leaveChannel, textChannels, config.leave_channel || "");
  elements.joinMessages.value = listToLines(config.join_messages);
  elements.leaveMessages.value = listToLines(config.leave_messages);
  elements.widgetEnabled.checked = Boolean(config.widget_enabled);
  renderWidgetPreview(guildId, config.widget_enabled);
}

function renderWidgetPreview(guildId, enabled) {
  elements.widgetPreview.innerHTML = "";
  if (!enabled) return;
  const iframe = document.createElement("iframe");
  iframe.src = `https://discord.com/widget?id=${guildId}&theme=dark`;
  iframe.width = "350";
  iframe.height = "500";
  iframe.allowTransparency = "true";
  iframe.frameBorder = "0";
  iframe.sandbox = "allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts";
  elements.widgetPreview.appendChild(iframe);
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
    announcement_channel: elements.announcementChannel.value || null,
    announcement_role: elements.announcementRole.value || null,
    join_channel: elements.joinChannel.value || null,
    join_messages: linesToList(elements.joinMessages.value),
    leave_channel: elements.leaveChannel.value || null,
    leave_messages: linesToList(elements.leaveMessages.value),
    widget_enabled: elements.widgetEnabled.checked,
  };
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/config`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    alert("settings saved");
    renderWidgetPreview(state.selectedGuild.id, elements.widgetEnabled.checked);
  } else {
    alert(result.error || "failed to save settings");
  }
}

function linesToList(value) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function listToLines(items) {
  return (items || []).join("\n");
}

async function loadModeration() {
  if (!state.selectedGuild) return;
  const guildId = state.selectedGuild.id;
  const [roles, channels, mod] = await Promise.all([
    fetchJson(`/api/guild/${guildId}/roles`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/channels`, { headers: authHeaders() }),
    fetchJson(`/api/guild/${guildId}/moderation`, { headers: authHeaders() }),
  ]);
  if (mod.error) {
    alert(mod.error);
    return;
  }
  fillSelect(elements.muteChannel, channels.filter((c) => c.type === "text"), mod.mute_channel || "");
  elements.requireConfirm.checked = Boolean(mod.require_confirm);
  elements.lockdownIncludeMemberRole.checked = Boolean(mod.lockdown_include_member_role);
  elements.warnDm.value = listToLines(mod.warn_dm);
  elements.warnChannel.value = listToLines(mod.warn_channel);
  elements.kickDm.value = listToLines(mod.kick_dm);
  elements.kickChannel.value = listToLines(mod.kick_channel);
  elements.banDm.value = listToLines(mod.ban_dm);
  elements.banChannel.value = listToLines(mod.ban_channel);
  elements.muteDm.value = listToLines(mod.mute_dm);
  elements.muteChannelMsg.value = listToLines(mod.mute_channel_msg);
}

async function saveModeration() {
  if (!state.selectedGuild) return;
  const payload = {
    mute_channel: elements.muteChannel.value || null,
    require_confirm: elements.requireConfirm.checked,
    lockdown_include_member_role: elements.lockdownIncludeMemberRole.checked,
    warn_dm: linesToList(elements.warnDm.value),
    warn_channel: linesToList(elements.warnChannel.value),
    kick_dm: linesToList(elements.kickDm.value),
    kick_channel: linesToList(elements.kickChannel.value),
    ban_dm: linesToList(elements.banDm.value),
    ban_channel: linesToList(elements.banChannel.value),
    mute_dm: linesToList(elements.muteDm.value),
    mute_channel_msg: linesToList(elements.muteChannelMsg.value),
  };
  const result = await fetchJson(`/api/guild/${state.selectedGuild.id}/moderation`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (result.ok) {
    alert("moderation settings saved");
  } else {
    alert(result.error || "failed to save moderation settings");
  }
}

function showActionsPanel() {
  showPanel(elements.actionsPanel);
}

function renderList(container, items, renderItem) {
  if (!container) return;
  container.innerHTML = "";
  items.forEach((item) => {
    container.appendChild(renderItem(item));
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
  hideAllPanels();
  setPanelVisible(elements.landingHero, true);
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

function initEvents() {
  elements.loginButton.addEventListener("click", () => {
    if (!state.clientId) {
      alert("this dashboard isn't fully configured yet — DISCORD_CLIENT_ID is missing on the bot.");
      return;
    }
    // Discord matches redirect_uri with exact string comparison — no normalizing
    // of trailing slashes. Always send bare origin (no path, no trailing slash)
    // and register *exactly* that in the Discord Developer Portal, e.g.
    // "http://localhost:8081" — not "http://localhost:8081/".
    const redirect = encodeURIComponent(window.location.origin);
    window.location.href = `https://discord.com/api/oauth2/authorize?client_id=${state.clientId}&redirect_uri=${redirect}&response_type=token&scope=identify%20guilds`;
  });

  elements.logoutButton.addEventListener("click", signOut);
  elements.backButton.addEventListener("click", () => showPanel(elements.configPanel));
  elements.actionsBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.saveConfig.addEventListener("click", saveConfig);
  elements.actionPanel.addEventListener("click", showActionsPanel);
  elements.ticketPanelsButton.addEventListener("click", () => showPanel(elements.ticketPanel));
  elements.containersButton.addEventListener("click", () => showPanel(elements.containersPanel));
  elements.moderationButton.addEventListener("click", () => showPanel(elements.moderationPanel));
  elements.ticketPanelBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.containersBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.moderationBack.addEventListener("click", () => showPanel(elements.configPanel));
  elements.createTicketPanel.addEventListener("click", createTicketPanel);
  elements.saveContainer.addEventListener("click", saveContainer);
  elements.saveModeration.addEventListener("click", saveModeration);
  document.querySelectorAll(".tile-action").forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action));
  });
}

function parseTokenFromHash() {
  const hash = window.location.hash.substring(1);
  const params = new URLSearchParams(hash);
  if (params.has("access_token")) {
    state.token = params.get("access_token");
    history.replaceState({}, document.title, window.location.pathname);
    elements.loginButton.hidden = true;
    loadGuilds();
  }
}

async function init() {
  await loadPublicConfig();
  // token parsing runs first and on its own — a bug in a click handler down
  // the line should never be able to eat the discord redirect again.
  parseTokenFromHash();
  try {
    initEvents();
  } catch (error) {
    console.error("failed to wire up dashboard controls", error);
  }
}

init();
