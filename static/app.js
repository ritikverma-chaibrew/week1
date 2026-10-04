"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* storage unavailable */ } },
};

const state = { options: null, mode: "free_conversation",
  scenario: null, focus: "recurring_mistakes", conversationId: null, sending: false };

const MODE_INFO = {
  free_conversation: {
    desc: "Chat about anything. Short feedback on every message.",
    icon: "M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z",
  },
  targeted_practice: {
    desc: "Drill one skill, like grammar or your recurring mistakes.",
    icon: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18ZM12 7a5 5 0 1 0 0 10a5 5 0 1 0 0-10ZM12 11a1 1 0 1 0 0 2a1 1 0 1 0 0-2Z",
  },
  workplace_english: {
    desc: "Role-play standups, code reviews, client meetings and more.",
    icon: "M4 8h16v11H4zM9 8V5h6v3M4 13h16",
  },
};
function modeIcon(id) {
  return svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, svg("path", { d: MODE_INFO[id].icon }));
}

/* Build DOM safely: all text goes through textContent, never innerHTML. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(child));
  }
  return el;
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  if (response.status === 204) return null;
  let data = null;
  try { data = await response.json(); } catch { /* non-JSON error body */ }
  if (!response.ok) {
    const err = new Error((data && data.detail) || "Something went wrong. Please try again.");
    err.status = response.status;
    throw err;
  }
  return data;
}

function relativeDay(iso) {
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

/* ---------- navigation ---------- */
const views = ["home", "practice", "progress", "guide"];
function route() {
  const name = location.hash.replace("#", "");
  const view = views.includes(name) ? name : "home";
  for (const v of views) $(`view-${v}`).hidden = v !== view;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  syncChatLayout();
  syncModeLinks();
  if (view === "home") loadHome();
  if (view === "progress") loadProgress();
  if (view === "practice") renderSetup();
  if (name !== "how") window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

/* Slim icon-only sidebar while a chat is open, to give the conversation room. */
function syncChatLayout() {
  const chatting = !!state.conversationId && !$("view-practice").hidden;
  document.querySelector(".shell").classList.toggle("compact", chatting);
  const layout = document.querySelector(".practice-layout");
  layout.classList.toggle("chatting", chatting);
  if (!chatting) layout.classList.remove("provider-open");
}

function syncModeLinks() {
  const onPractice = !$("view-practice").hidden;
  document.querySelectorAll("[data-mode]").forEach((a) => {
    if (onPractice && a.dataset.mode === state.mode) a.setAttribute("aria-current", "true");
    else a.removeAttribute("aria-current");
  });
}
/* Sidebar mode links: jump straight to the mode picker with that mode selected. */
document.querySelectorAll("[data-mode]").forEach((a) => a.addEventListener("click", (e) => {
  state.mode = a.dataset.mode;
  if (state.conversationId) resetChat();
  if (location.hash === "#practice") { e.preventDefault(); setMenu(false); renderSetup(); syncModeLinks(); }
}));

/* ---------- mobile sidebar drawer ---------- */
function setMenu(open) {
  $("sidebar").classList.toggle("open", open);
  $("scrim").hidden = !open;
  $("menu-toggle").setAttribute("aria-expanded", String(open));
}
$("menu-toggle").addEventListener("click", () => setMenu(!$("sidebar").classList.contains("open")));
$("scrim").addEventListener("click", () => setMenu(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });
window.addEventListener("hashchange", () => setMenu(false));

/* ---------- AI connection: single source of truth ----------
   Every piece of UI that shows the connection (banner, sidebar badge, status card, Connect
   button, Start button) renders from `ai.state` via ai.subscribe(); nothing else stores it.
   The browser keeps the chosen connection in localStorage until the user deletes it, and
   silently re-connects whenever the server has forgotten it (restart, idle expiry). */
const SAVED_AI = "ai-connection"; // { mode, apiKey, model, expires }
const KEY_TTL_MS = 30 * 60 * 1000; // a saved Google key is deleted from the browser after 30 minutes
const ai = {
  state: { status: "checking", mode: null, provider: "", model: "", keyMasked: null, error: "", keyExpires: null },
  listeners: [],
  set(patch) {
    Object.assign(this.state, patch);
    for (const fn of this.listeners) fn(this.state);
  },
  subscribe(fn) { this.listeners.push(fn); fn(this.state); },
  get connected() { return this.state.status === "connected"; },
};

function readSaved() {
  try {
    const v = JSON.parse(store.get(SAVED_AI) || "null");
    if (v && v.mode === "lmstudio") return v;
    if (v && v.mode === "google" && v.expires > Date.now()) return v;
  } catch { /* corrupt entry */ }
  store.remove(SAVED_AI); // missing, corrupt or expired
  return null;
}
/* The 30-minute clock starts when the key is first saved; reconnecting doesn't restart it. */
function writeSaved(v, { keepExpiry = false } = {}) {
  const old = keepExpiry ? readSaved() : null;
  const expires = v.mode === "google" ? (old && old.apiKey === v.apiKey ? old.expires : Date.now() + KEY_TTL_MS) : null;
  store.set(SAVED_AI, JSON.stringify({ ...v, expires }));
}
// one-time migration from the earlier storage format
(() => {
  try {
    const old = JSON.parse(store.get("provider-google-key") || "null");
    if (old && old.key && old.expires > Date.now() && !readSaved()) {
      store.set(SAVED_AI, JSON.stringify({ mode: "google", apiKey: old.key, model: "", expires: old.expires }));
    }
  } catch { /* ignore */ }
  store.remove("provider-google-key");
  store.remove("provider-mode");
})();

function applyServerStatus(p) {
  if (p.connected) {
    const saved = readSaved();
    ai.set({ status: "connected", mode: p.mode, provider: p.provider, model: p.model || "",
      keyMasked: p.key_masked, error: "", keyExpires: p.mode === "google" && saved ? saved.expires : null });
  } else {
    ai.set({ status: "disconnected", mode: null, provider: "", model: "", keyMasked: null, error: "", keyExpires: null });
  }
}

/* Ask the server what it is using; restore the saved connection if the server lost it. */
async function refreshAI({ restore = true } = {}) {
  let p;
  try { p = await api("/api/session/provider"); } catch (err) {
    ai.set({ status: "error", error: err.message });
    return;
  }
  const saved = readSaved();
  const serverHasUserChoice = p.connected && p.mode !== "server";
  if (p.connected && p.mode === "google" && !saved) {
    // the browser copy expired (or was deleted): the server must not keep using the key
    await api("/api/session/provider", { method: "DELETE" }).catch(() => {});
    p = await api("/api/session/provider").catch(() => ({ connected: false }));
  } else if (!serverHasUserChoice && saved && restore) {
    await connectAI(saved, { silent: true });
    return;
  }
  applyServerStatus(p);
}

async function connectAI({ mode, apiKey = "", model = "" }, { silent = false } = {}) {
  ai.set({ status: "connecting", error: "" });
  try {
    await api("/api/session/provider", { method: "PUT", body: JSON.stringify({ mode, api_key: apiKey, model }) });
    writeSaved({ mode, apiKey: mode === "google" ? apiKey : "", model }, { keepExpiry: silent });
    applyServerStatus(await api("/api/session/provider"));
    return true;
  } catch (err) {
    ai.set({ status: "error", mode: null, provider: "", model: "", keyMasked: null,
      error: silent ? `Your saved ${mode === "google" ? "API key" : "LM Studio connection"} couldn't reconnect: ${err.message}` : err.message });
    return false;
  }
}

/* Delete the key when its 30 minutes are up, even if the page stays open. */
setInterval(async () => {
  const st = ai.state;
  if (st.mode !== "google" || !st.keyExpires) return;
  if (st.keyExpires <= Date.now()) {
    await disconnectAI();
    ai.set({ status: "error", error: "Your API key was deleted after 30 minutes. Paste it again to keep practising." });
  } else {
    ai.set({}); // re-render the countdown
  }
}, 15000);

async function disconnectAI() {
  await api("/api/session/provider", { method: "DELETE" }).catch(() => {});
  store.remove(SAVED_AI);
  $("byok-input").value = "";
  await refreshAI({ restore: false });
  loadModels();
}

/* Run an AI request; if the server forgot the connection, restore it once and retry. */
async function withAI(request) {
  try {
    return await request();
  } catch (err) {
    if (err.status !== 503 || !readSaved()) throw err;
    // A 503 is usually a model problem (timeout, bad output). Only reconnect when the server
    // has really lost the user's connection; otherwise show the error and keep the state as is.
    const p = await api("/api/session/provider").catch(() => null);
    if (!p || (p.connected && p.mode !== "server")) throw err;
    if (!(await connectAI(readSaved(), { silent: true }))) throw err;
    return request();
  }
}

/* ---------- global renderers: these run on every page ---------- */
const NOT_CONNECTED = "The coach is not available right now. It will be available once you connect an API key (or LM Studio).";
ai.subscribe((st) => {
  const banner = $("banner");
  const problem = st.status === "disconnected" || st.status === "error";
  banner.hidden = !problem;
  $("banner-text").textContent = st.status === "error" ? st.error : NOT_CONNECTED;
});
ai.subscribe((st) => {
  const badge = $("ai-badge");
  const label = {
    checking: "Checking coach…",
    connecting: "Connecting…",
    connected: "Coach connected",
    disconnected: "Coach not connected",
    error: "Coach not connected",
  }[st.status];
  badge.dataset.status = st.status;
  badge.replaceChildren(h("span", { class: "dot", "aria-hidden": "true" }),
    h("span", { class: "badge-text" }, h("strong", {}, label),
      st.status === "connected" ? h("small", {}, `${st.provider} · ${st.model || "default model"}`) : null));
  badge.title = st.status === "connected" ? `${label}: ${st.provider}, ${st.model}` : label;
  $("ai-dot").dataset.status = st.status;
  $("ai-dot").setAttribute("aria-label", label);
});
let lastStatus = null;
ai.subscribe((st) => { // the Start button depends on the status, so re-render only when it changes
  if (st.status === lastStatus) return;
  lastStatus = st.status;
  if (!$("view-practice").hidden && !state.conversationId) renderSetup();
});

/* Take the user to the provider panel, open it and put the cursor where they need to type. */
function showProviderPanel() {
  const go = () => {
    const details = $("byok-details");
    details.closest(".practice-layout").classList.add("provider-open"); // hidden during a chat
    details.open = true;
    const panel = details.closest(".provider-panel");
    panel.classList.remove("attention");
    void panel.offsetWidth; // restart the highlight animation
    panel.classList.add("attention");
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    ($("provider-mode").value === "google" ? $("byok-input") : $("provider-model")).focus({ preventScroll: true });
  };
  if (location.hash !== "#practice") { location.hash = "#practice"; setTimeout(go, 50); } else go();
}
$("banner-connect").addEventListener("click", showProviderPanel);
for (const id of ["ai-badge", "ai-dot"]) {
  $(id).addEventListener("click", (e) => { e.preventDefault(); setMenu(false); showProviderPanel(); });
}
ai.subscribe((st) => { // once connected mid-chat, tuck the provider panel away again
  if (st.status === "connected") document.querySelector(".practice-layout").classList.remove("provider-open");
});

/* ---------- home ---------- */
function dataNote(p) {
  const q = p.data_quality;
  if (!q || q.level === "reliable") return null;
  return h("p", { class: q.level === "none" ? "data-note empty-state" : "data-note", role: "note" }, q.message);
}

async function loadHome() {
  const box = $("home-summary");
  try {
    const p = await api("/api/progress");
    box.replaceChildren();
    if (!p.has_data && !p.recurring_mistakes.length) {
      box.append(h("p", {}, "Not enough data yet. Start a conversation and your coach will begin remembering how you communicate."));
      return;
    }
    const top = p.recurring_mistakes[0];
    box.append(
      top
        ? h("p", {}, h("strong", {}, "Recurring weakness: "), `${top.label} (${top.frequency} times)`)
        : h("p", {}, "No recurring weakness yet."),
      dataNote(p),
      h("p", { class: "muted" }, `${p.recent_sessions.length} recent session(s). `,
        h("a", { href: "#progress" }, "See full progress"))
    );
  } catch (err) {
    box.textContent = err.message;
  }
}

/* ---------- practice setup ---------- */
async function loadOptions() {
  if (!state.options) state.options = await api("/api/practice/modes");
  return state.options;
}

async function renderSetup() {
  $("setup").hidden = !!state.conversationId;
  $("chat").hidden = !state.conversationId;
  if (state.conversationId) return;
  const options = await loadOptions();
  const select = (id) => { state.mode = id; renderSetup(); syncModeLinks(); };
  $("mode-tabs").replaceChildren(...options.modes.map((m) =>
    h("button", { type: "button", role: "radio", class: "mode-card", "aria-checked": String(m.id === state.mode),
      onclick: () => select(m.id) },
      h("span", { class: "mode-icon" }, modeIcon(m.id)),
      h("strong", {}, m.label),
      h("span", { class: "desc" }, MODE_INFO[m.id].desc))));

  const panel = $("mode-panel");
  const label = options.modes.find((m) => m.id === state.mode).label;
  panel.replaceChildren(h("div", { class: "coach-intro" }, coachAvatar(false, true),
    h("p", {}, `Great choice: ${label}. `, MODE_INFO[state.mode].desc)));
  if (state.mode === "targeted_practice") {
    panel.append(h("h2", { class: "step-title" }, h("span", { class: "step-num" }, "2"), "Pick what to work on"),
      h("p", { class: "muted small" }, "\"Recurring Mistakes\" uses the patterns your coach has remembered."),
      h("div", { class: "choices" }, options.focuses.map((f) =>
        h("button", { type: "button", class: "choice", "aria-pressed": String(state.focus === f.id),
          onclick: () => { state.focus = f.id; renderSetup(); } }, h("strong", {}, f.label)))));
  } else if (state.mode === "workplace_english") {
    state.scenario = state.scenario || options.scenarios[0].id;
    panel.append(h("h2", { class: "step-title" }, h("span", { class: "step-num" }, "2"), "Pick a situation"),
      h("div", { class: "choices" }, options.scenarios.map((sc) =>
        h("button", { type: "button", class: "choice", "aria-pressed": String(state.scenario === sc.id),
          onclick: () => { state.scenario = sc.id; renderSetup(); } },
          h("strong", {}, sc.title), h("span", {}, sc.prompt)))));
  }
  const row = h("div", { class: "start-row" },
    h("button", { type: "button", class: "btn btn-primary", id: "start-btn", onclick: startPractice,
      disabled: !ai.connected }, "Start practice"));
  if (!ai.connected && ai.state.status !== "checking" && ai.state.status !== "connecting") {
    row.append(h("p", { class: "start-hint", role: "note" }, "The coach isn't connected yet. ",
      h("a", { href: "#practice", onclick: (e) => { e.preventDefault(); showProviderPanel(); } }, "Connect an AI provider"),
      " to start."));
  }
  panel.append(row);
}

async function startPractice(event) {
  const button = event.currentTarget;
  button.disabled = true;
  button.replaceChildren("Coach is thinking", h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")));
  const body = { mode: state.mode };
  if (state.mode === "workplace_english") body.scenario = state.scenario;
  if (state.mode === "targeted_practice") body.focus = state.focus;
  try {
    const data = await withAI(() => api("/api/practice/start", { method: "POST", body: JSON.stringify(body) }));
    openChat(data);
  } catch (err) {
    button.disabled = false;
    button.textContent = "Start practice";
    $("mode-panel").append(h("p", { class: "error", role: "alert" }, err.message));
  }
}

/* ---------- chat ---------- */
function renderTryModes() {
  const others = (state.options ? state.options.modes : []).filter((m) => m.id !== state.mode);
  const current = state.options && state.options.modes.find((m) => m.id === state.mode);
  $("chat-mode").textContent = current ? current.label : "";
  $("try-modes").replaceChildren(...(others.length ? [h("span", {}, "Try another mode:"),
    ...others.map((m) => h("button", { type: "button", class: "try-chip",
      onclick: () => { state.mode = m.id; resetChat(); renderSetup(); syncModeLinks(); window.scrollTo(0, 0); } },
      m.label, " →"))] : []));
}

function openChat(data) {
  state.conversationId = data.conversation.id;
  if (data.conversation.mode) state.mode = data.conversation.mode;
  renderTryModes();
  $("chat-title").textContent = data.conversation.title;
  $("chat-sub").textContent = data.notice || data.conversation.focus_label || "";
  $("messages").replaceChildren();
  data.messages.forEach((m) => addMessage(m.role, m.content, m.feedback));
  $("setup").hidden = true;
  $("chat").hidden = false;
  syncChatLayout();
  $("input").focus();
}

function resetChat() {
  state.conversationId = null;
  $("messages").replaceChildren();
  $("chat-error").hidden = true;
  syncChatLayout();
}
document.querySelector("[data-nav=practice]").addEventListener("click", () => {
  if (state.conversationId && location.hash === "#practice") { resetChat(); renderSetup(); }
});
$("new-session").addEventListener("click", () => { resetChat(); renderSetup(); });

/* Cute full-body human coach (glasses, indigo sweater, whistle), drawn as inline SVG. */
const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  el.append(...children);
  return el;
}

function coachAvatar(thinking = false, large = false) {
  const skin = "#ffd9b3", hair = "#4a2f27", ink = "#2b2540", pink = "#ff9db4";
  const sweater = "#4f46e5", pants = "#3a3358";
  const eye = (cx) => svg("g", { class: "eye" },
    svg("ellipse", { cx, cy: 29, rx: 1.9, ry: 2.5, fill: ink }),
    svg("circle", { cx: cx + 0.7, cy: 28.1, r: 0.7, fill: "#fff" }));
  return svg("svg", { viewBox: "0 0 64 96", class: `avatar${thinking ? " thinking" : ""}${large ? " large" : ""}`,
    "aria-hidden": "true", focusable: "false" },
    svg("rect", { x: 24, y: 70, width: 7, height: 18, rx: 3, fill: pants }),
    svg("rect", { x: 33, y: 70, width: 7, height: 18, rx: 3, fill: pants }),
    svg("ellipse", { cx: 26, cy: 89, rx: 6.5, ry: 3.5, fill: ink }),
    svg("ellipse", { cx: 38, cy: 89, rx: 6.5, ry: 3.5, fill: ink }),
    svg("rect", { x: 18, y: 46, width: 28, height: 30, rx: 10, fill: sweater }),
    svg("rect", { x: 18, y: 68, width: 28, height: 8, rx: 4, fill: pants }),
    svg("path", { d: "M26 46 L32 55 L38 46 Z", fill: "#fff" }),
    svg("path", { d: "M27 47 Q32 62 37 47", fill: "none", stroke: "#ffc94d", "stroke-width": 1 }),
    svg("circle", { cx: 32, cy: 61, r: 2.6, fill: "#ffc94d" }),
    svg("rect", { x: 29, y: 40, width: 6, height: 8, rx: 2, fill: skin }),
    svg("rect", { x: 10, y: 48, width: 8, height: 22, rx: 4, fill: sweater, transform: "rotate(6 14 50)" }),
    svg("circle", { cx: 12, cy: 71, r: 4, fill: skin }),
    svg("g", { class: "wave" },
      svg("rect", { x: 46, y: 48, width: 8, height: 22, rx: 4, fill: sweater, transform: "rotate(-6 50 50)" }),
      svg("circle", { cx: 52, cy: 71, r: 4, fill: skin })),
    svg("ellipse", { cx: 32, cy: 24, rx: 19, ry: 18, fill: hair }),
    svg("circle", { cx: 16, cy: 31, r: 3, fill: skin }),
    svg("circle", { cx: 48, cy: 31, r: 3, fill: skin }),
    svg("circle", { cx: 32, cy: 28, r: 16, fill: skin }),
    svg("path", { d: "M15.5 27 Q16 10 32 10 Q48 10 48.5 27 Q42 16 34 18 Q26 14 15.5 27 Z", fill: hair }),
    eye(25.5), eye(38.5),
    svg("circle", { cx: 25.5, cy: 29, r: 5.4, fill: "none", stroke: ink, "stroke-width": 1.2 }),
    svg("circle", { cx: 38.5, cy: 29, r: 5.4, fill: "none", stroke: ink, "stroke-width": 1.2 }),
    svg("path", { d: "M30.9 29 H33.1", stroke: ink, "stroke-width": 1.2 }),
    svg("ellipse", { cx: 20.5, cy: 36, rx: 2.8, ry: 1.8, fill: pink, opacity: 0.75 }),
    svg("ellipse", { cx: 43.5, cy: 36, rx: 2.8, ry: 1.8, fill: pink, opacity: 0.75 }),
    svg("path", { class: "mouth-smile", d: "M28 36 Q32 40.5 36 36", fill: "none", stroke: ink, "stroke-width": 1.4, "stroke-linecap": "round" }),
    svg("ellipse", { class: "mouth-o", cx: 32, cy: 37.5, rx: 1.9, ry: 2.3, fill: ink }));
}

function typingBubble() {
  const dots = h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i"));
  return h("div", { class: "row assistant typing" }, coachAvatar(true),
    h("div", { class: "bubble" }, h("span", { class: "typing-text" }, "Coach is thinking"), dots));
}

function addMessage(role, text, feedback) {
  const row = h("div", { class: `row ${role}` },
    role === "assistant" && coachAvatar(),
    h("div", { class: "bubble" }, text));
  if (feedback) attachFeedback(row, feedback);
  $("messages").append(row);
  scrollDown();
  return row;
}

function scrollDown() {
  const box = $("messages");
  box.scrollTop = box.scrollHeight;
}

function attachFeedback(row, fb) {
  for (const pattern of fb.patterns || []) {
    row.append(h("div", { class: "pattern" }, h("strong", {}, "Recurring pattern detected: "),
      `${pattern.label}. You've made this mistake ${pattern.frequency} times. Try the sentence again.`));
  }
  if (!fb.available) {
    row.append(h("p", { class: "muted small" }, "Feedback wasn't available for this message."));
    return;
  }
  const items = fb.mistakes.map((m) => h("div", { class: "feedback-item" },
    h("dl", {},
      h("dt", {}, "Pattern"), h("dd", {}, m.category.replace(/_/g, " ")),
      h("dt", {}, "Better"), h("dd", {}, `"${m.correction}"`),
      h("dt", {}, "Why"), h("dd", {}, m.explanation))));
  const body = h("div", { class: "feedback-body" });
  if (fb.changed) body.append(h("dl", {}, h("dt", {}, "Natural version"), h("dd", {}, `"${fb.corrected_text}"`)));
  body.append(...items);
  if (!fb.mistakes.length) body.append(h("p", { class: "good" }, "Nicely said. No important mistakes."));
  if (fb.practice_suggestion) body.append(h("p", { class: "muted" }, fb.practice_suggestion));
  row.append(h("details", { class: "feedback", open: true }, h("summary", {}, "Coach feedback"), body));
}

function setSending(sending) {
  state.sending = sending;
  $("send").disabled = sending;
  $("send").textContent = sending ? "Sending…" : "Send";
}

async function submitMessage(event) {
  event.preventDefault();
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.sending || !state.conversationId) return;
  $("chat-error").hidden = true;
  setSending(true);
  const userRow = addMessage("user", text);
  input.value = "";
  const typing = typingBubble();
  $("messages").append(typing);
  scrollDown();
  try {
    const data = await withAI(() => api(`/api/conversations/${state.conversationId}/messages`,
      { method: "POST", body: JSON.stringify({ content: text }) }));
    typing.remove();
    addMessage("assistant", data.reply);
    attachFeedback(userRow, data.feedback);
    scrollDown();
  } catch (err) {
    typing.remove();
    userRow.remove();
    input.value = text;
    $("chat-error").textContent = err.message;
    $("chat-error").hidden = false;
  } finally {
    setSending(false);
    input.focus();
  }
}
$("composer").addEventListener("submit", submitMessage);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

/* ---------- AI provider panel (renders from the store) ---------- */
ai.subscribe((st) => {
  const box = $("provider-status");
  box.dataset.status = st.status;
  if (st.status === "checking" || st.status === "connecting") {
    box.replaceChildren(h("p", { class: "muted" }, st.status === "checking" ? "Checking connection…" : "Connecting…"));
    return;
  }
  if (st.status !== "connected") {
    box.replaceChildren(h("p", { class: st.status === "error" ? "error small" : "muted" },
      st.status === "error" ? st.error : "No AI provider connected yet. Choose one below and press Connect."));
    if (readSaved()) {
      box.append(h("div", { class: "actions" },
        h("button", { type: "button", class: "btn btn-ghost btn-small", onclick: () => connectAI(readSaved()) }, "Retry"),
        h("button", { type: "button", class: "btn btn-ghost btn-small", onclick: disconnectAI }, "Delete saved key")));
    }
    return;
  }
  const lines = [h("strong", {}, h("span", { class: "dot", "aria-hidden": "true" }), ` Connected to ${st.provider}`),
    h("span", {}, "Model: ", h("code", {}, st.model || "default"))];
  if (st.keyMasked) lines.push(h("span", {}, "API key: ", h("code", {}, st.keyMasked)));
  if (st.mode === "google" && st.keyExpires) {
    const mins = Math.max(1, Math.ceil((st.keyExpires - Date.now()) / 60000));
    lines.push(h("span", { class: "muted small" }, `The API key will be deleted from this browser in ${mins} minute${mins === 1 ? "" : "s"}.`));
  } else if (st.mode === "lmstudio") {
    lines.push(h("span", { class: "muted small" }, "Saved in this browser until you disconnect."));
  }
  box.replaceChildren(h("div", { class: "info" }, ...lines));
  if (st.mode !== "server") {
    box.append(h("button", { type: "button", class: "btn btn-ghost btn-small", onclick: disconnectAI },
      st.keyMasked ? "Delete API key" : "Disconnect"));
  }
});

/* The form's values vs. the live connection: Connect is only enabled when something changed. */
function formValues() {
  return { mode: $("provider-mode").value, apiKey: $("byok-input").value.trim(), model: $("provider-model").value };
}
function formMatchesConnection() {
  const saved = readSaved();
  const f = formValues();
  return ai.connected && saved && saved.mode === f.mode && f.model === ai.state.model
    && (f.mode !== "google" || f.apiKey === saved.apiKey);
}
function syncConnectButton() {
  const button = $("byok-connect");
  const st = ai.state;
  const same = formMatchesConnection();
  const busy = st.status === "connecting" || st.status === "checking";
  button.disabled = busy || same || !$("provider-model").value;
  button.textContent = st.status === "connecting" ? "Connecting…" : same ? "Connected ✓" : ai.connected ? "Switch" : "Connect";
  $("byok-clear").hidden = !readSaved() && !(ai.connected && st.mode !== "server");
}
ai.subscribe((st) => {
  const status = $("byok-status");
  if (st.status === "error") { status.textContent = st.error; status.className = "error small"; }
  else if (st.status === "connected") { status.textContent = ""; status.className = "muted small"; }
  syncConnectButton();
});

async function loadModels() {
  const mode = $("provider-mode").value;
  const select = $("provider-model");
  const status = $("byok-status");
  select.disabled = true;
  try {
    const data = await api("/api/session/models", { method: "POST", body: JSON.stringify({ mode, api_key: $("byok-input").value.trim() }) });
    if ($("provider-mode").value !== mode) return; // user switched meanwhile
    const saved = readSaved();
    const preferred = saved && saved.mode === mode && saved.model ? saved.model : data.default;
    if (data.models.length) {
      select.replaceChildren(...data.models.map((m) => h("option", { value: m }, m)));
      select.value = data.models.includes(preferred) ? preferred : data.models[0];
    } else if (mode === "lmstudio" && data.default) {
      select.replaceChildren(h("option", { value: preferred }, preferred));
    } else {
      select.replaceChildren(h("option", { value: "" }, "Paste your key to load models"));
    }
    if (ai.state.status !== "error") {
      status.textContent = data.error || "";
      status.className = data.error ? "error small" : "muted small";
    }
  } catch (err) {
    status.textContent = err.message;
    status.className = "error small";
  } finally {
    select.disabled = !select.value;
    syncConnectButton();
  }
}
$("model-refresh").addEventListener("click", loadModels);
$("byok-input").addEventListener("change", loadModels); // key pasted: load the models it can use
$("byok-input").addEventListener("input", syncConnectButton);
$("provider-model").addEventListener("change", syncConnectButton);
function syncProviderForm() {
  const mode = $("provider-mode").value;
  $("google-fields").hidden = mode !== "google";
  $("local-note").hidden = mode !== "lmstudio";
  loadModels();
}
(() => { // fill the form from the saved connection
  const saved = readSaved();
  if (saved) {
    $("provider-mode").value = saved.mode;
    $("byok-input").value = saved.apiKey || "";
  }
})();
$("provider-mode").addEventListener("change", syncProviderForm);
syncProviderForm();

$("byok-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = formValues();
  $("byok-status").textContent = f.mode === "google" ? "Checking your key…" : "Connecting to LM Studio…";
  $("byok-status").className = "muted small";
  if (await connectAI(f)) {
    $("byok-status").textContent = f.mode === "google" ? "Connected to Google AI Studio." : "Connected to LM Studio.";
  }
});
$("byok-clear").addEventListener("click", async () => {
  await disconnectAI();
  $("byok-status").textContent = "Disconnected. Saved key removed.";
  $("byok-status").className = "muted small";
});

/* ---------- progress ---------- */
async function loadProgress() {
  const body = $("progress-body");
  try {
    const p = await api("/api/progress");
    $("disclaimer").textContent = p.disclaimer;
    body.replaceChildren(...[
      dataNote(p),
      skillsSection(p), mistakesSection(p), strengthsSection(p), sessionsSection(p)].filter(Boolean));
  } catch (err) {
    body.replaceChildren(h("p", { class: "error", role: "alert" }, err.message));
  }
}

function skillsSection(p) {
  return h("div", { class: "skills" }, p.skills.map((s) => {
    const meter = h("span");
    meter.style.width = `${s.score ?? 0}%`;
    return h("div", { class: "card" }, h("div", { class: "muted" }, s.label),
      h("div", { class: "skill-score" }, s.score == null ? "–" : `${s.score}%`),
      h("div", { class: "meter", role: "img", "aria-label": `${s.label} ${s.score ?? "not enough data"}` }, meter),
      s.score == null && h("p", { class: "muted small" }, "Not enough data"));
  }));
}

function mistakesSection(p) {
  const max = Math.max(1, ...p.recurring_mistakes.map((m) => m.frequency));
  const rows = p.recurring_mistakes.map((m) => {
    const fill = h("span");
    fill.style.width = `${(m.frequency / max) * 100}%`;
    return h("div", { class: "bar-row" }, h("span", {}, m.label), h("div", { class: "meter" }, fill),
      h("span", { class: "trend" }, m.trend ? `${m.trend.previous} → ${m.trend.current} (week over week)` : `${m.frequency}×`));
  });
  return h("section", { class: "card section" }, h("h2", {}, "Recurring mistakes"),
    rows.length ? rows : h("p", { class: "muted" }, "Not enough data yet. Mistakes from your practice messages will appear here."));
}

function strengthsSection(p) {
  return h("section", { class: "card section" }, h("h2", {}, "Strengths"),
    p.strengths.length
      ? h("ul", { class: "plain" }, p.strengths.map((s) => h("li", { class: "good" }, `✓ ${s}`)))
      : h("p", { class: "muted" }, "Not enough data yet. Strengths appear after your first evaluated message."));
}

function sessionsSection(p) {
  return h("section", { class: "card section" }, h("h2", {}, "Recent practice"),
    p.recent_sessions.length
      ? h("ul", { class: "plain sessions" }, p.recent_sessions.map((s) =>
          h("li", {}, h("span", {}, s.title), h("span", { class: "muted" }, relativeDay(s.updated_at)))))
      : h("p", { class: "muted" }, "No sessions yet."));
}

/* ---------- boot ---------- */
route();
refreshAI();
