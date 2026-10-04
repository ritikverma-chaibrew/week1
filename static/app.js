"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* storage unavailable */ } },
};

const state = { options: null, mode: "free_conversation",
  scenario: null, focus: "recurring_mistakes", conversationId: null, sending: false };

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
    throw new Error((data && data.detail) || "Something went wrong. Please try again.");
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
}

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

/* ---------- status banners ---------- */
async function loadHealth() {
  const banner = $("banner");
  try {
    const data = await api("/api/health");
    banner.hidden = !data.ai_message;
    banner.textContent = data.ai_message || "";
  } catch {
    banner.hidden = true;
  }
}

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
  const tabs = $("mode-tabs");
  tabs.replaceChildren(...options.modes.map((m) =>
    h("button", { type: "button", role: "tab", class: "tab", "aria-selected": String(m.id === state.mode),
      onclick: () => { state.mode = m.id; renderSetup(); } }, m.label)));
  const panel = $("mode-panel");
  panel.replaceChildren(h("div", { class: "coach-intro" }, coachAvatar(false, true),
    h("p", {}, "Hi, I'm your English coach! Pick a way to practice and I'll help you sound natural at work.")));
  if (state.mode === "free_conversation") {
    panel.append(h("p", {}, "Talk or write about anything. Your coach replies naturally and gives short feedback on your English."));
  } else if (state.mode === "targeted_practice") {
    panel.append(h("p", {}, "Pick what to work on. \"Recurring Mistakes\" uses your stored patterns."),
      h("div", { class: "choices" }, options.focuses.map((f) =>
        h("button", { type: "button", class: "choice", "aria-pressed": String(state.focus === f.id),
          onclick: () => { state.focus = f.id; renderSetup(); } }, h("strong", {}, f.label)))));
  } else {
    state.scenario = state.scenario || options.scenarios[0].id;
    panel.append(h("div", { class: "choices" }, options.scenarios.map((s) =>
      h("button", { type: "button", class: "choice", "aria-pressed": String(state.scenario === s.id),
        onclick: () => { state.scenario = s.id; renderSetup(); } },
        h("strong", {}, s.title), h("span", {}, s.prompt)))));
  }
  panel.append(h("button", { type: "button", class: "btn btn-primary", id: "start-btn", onclick: startPractice }, "Start practice"));
}

async function startPractice(event) {
  const button = event.currentTarget;
  button.disabled = true;
  button.replaceChildren("Coach is thinking", h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")));
  const body = { mode: state.mode };
  if (state.mode === "workplace_english") body.scenario = state.scenario;
  if (state.mode === "targeted_practice") body.focus = state.focus;
  try {
    const data = await api("/api/practice/start", { method: "POST", body: JSON.stringify(body) });
    openChat(data);
  } catch (err) {
    button.disabled = false;
    button.textContent = "Start practice";
    $("mode-panel").append(h("p", { class: "error", role: "alert" }, err.message));
  }
}

/* ---------- chat ---------- */
function openChat(data) {
  state.conversationId = data.conversation.id;
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
  row.append(h("details", { class: "feedback", open: fb.mistakes.length > 0 }, h("summary", {}, "Coach feedback"), body));
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
    const data = await api(`/api/conversations/${state.conversationId}/messages`,
      { method: "POST", body: JSON.stringify({ content: text }) });
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

/* ---------- optional bring-your-own-key ---------- */
$("byok-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("byok-input");
  try {
    await api("/api/session/key", { method: "PUT", body: JSON.stringify({ api_key: input.value }) });
    input.value = "";
    loadHealth();
  } catch (err) {
    alert(err.message);
  }
});
$("byok-clear").addEventListener("click", async () => {
  await api("/api/session/key", { method: "DELETE" }).catch(() => {});
  loadHealth();
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
loadHealth();
route();
