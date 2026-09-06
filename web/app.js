const feedEl = document.getElementById("feed");
const detailEl = document.getElementById("detail");
const detailContentEl = document.getElementById("detailContent");
const logViewEl = document.getElementById("logView");
const logListEl = document.getElementById("logList");
const logDateEl = document.getElementById("logDate");

let currentDetailEntity = null;
let currentDetailTodoId = null;

// ---- view/interaction tracking ----

function logView(entityId, durationMs, context) {
  if (!entityId || durationMs < 1000) return;
  fetch(`/api/entity/${entityId}/view`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: Math.round(durationMs), context }),
    keepalive: true,
  }).catch(() => {});
}

function logInteraction(entityId, action) {
  if (!entityId) return;
  fetch(`/api/entity/${entityId}/interact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
    keepalive: true,
  }).catch(() => {});
}

const cardEnterTimes = new Map();

function flushOpenCardViews() {
  const now = Date.now();
  cardEnterTimes.forEach((enteredAt, entityId) => {
    logView(entityId, now - enteredAt, "card");
  });
  cardEnterTimes.clear();
}

let detailViewEntityId = null;
let detailViewStart = null;

function flushDetailView() {
  if (detailViewEntityId && detailViewStart) {
    logView(detailViewEntityId, Date.now() - detailViewStart, "detail");
  }
  detailViewEntityId = null;
  detailViewStart = null;
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    flushOpenCardViews();
    flushDetailView();
  }
});

function formatTs(iso) {
  return (iso || "").replace("T", " ").slice(0, 16);
}

const TYPE_COLORS = {
  paper: "var(--sig-paper)",
  person: "var(--sig-person)",
  repo: "var(--sig-repo)",
  job: "var(--sig-job)",
};

function typeColor(type) {
  return TYPE_COLORS[type] || "var(--sig-default)";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function signalBarsHtml(noveltyScore) {
  const score = Math.max(0, Math.min(1, Number(noveltyScore) || 0));
  const filled = Math.max(1, Math.round(score * 5));
  const bars = Array.from({ length: 5 }, (_, i) => `<span class="${i < filled ? "on" : ""}"></span>`).join("");
  return `<span class="signal-bars">${bars}</span>`;
}

function metaRowHtml(entity, index) {
  const entryNo = String(index + 1).padStart(3, "0");
  return `
    <div class="meta-row" style="color: ${typeColor(entity.type)}">
      <span>LOG ${escapeHtml(entity.last_seen_date || "")} · #${entryNo}</span>
      ${signalBarsHtml(entity.novelty_score)}
    </div>`;
}

function renderExtra(extra) {
  return Object.entries(extra || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<div class="extra-row"><b>${escapeHtml(k)}:</b> ${escapeHtml(v)}</div>`)
    .join("");
}

function cardHtml(entity, index) {
  return `
    <div class="card" data-id="${entity.id}">
      <button class="card-add-btn" data-add-id="${entity.id}" aria-label="Add to todo">[ + ]</button>
      ${metaRowHtml(entity, index)}
      <span class="type-tag" style="color: ${typeColor(entity.type)}">[${escapeHtml(entity.type)}]</span>
      <h2 class="card-title">${escapeHtml(entity.one_liner || entity.title)}</h2>
      <div class="card-hint">tap for detail</div>
    </div>`;
}

function detailHtml(entity, index) {
  const tags = (entity.tags || []).map((t) => `<span>${escapeHtml(t)}</span>`).join("");
  const link = entity.raw_url
    ? `<a class="source-link" href="${escapeHtml(entity.raw_url)}" target="_blank" rel="noopener">[ open source → ]</a>`
    : "";
  return `
    ${metaRowHtml(entity, index ?? 0)}
    <span class="type-tag" style="color: ${typeColor(entity.type)}">[${escapeHtml(entity.type)}]</span>
    <h1>${escapeHtml(entity.title)}</h1>
    <p>${escapeHtml(entity.summary || entity.one_liner || "")}</p>
    <div class="detail-tags">${tags}</div>
    ${renderExtra(entity.extra)}
    ${link}
    <button id="detailAddTodo" class="add-todo-btn">[ add to todo ]</button>
  `;
}

let feedEntities = [];

function observeCards() {
  const cards = document.querySelectorAll(".card");
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const entityId = entry.target.dataset.id;
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          if (!cardEnterTimes.has(entityId)) cardEnterTimes.set(entityId, Date.now());
        } else if (cardEnterTimes.has(entityId)) {
          const enteredAt = cardEnterTimes.get(entityId);
          cardEnterTimes.delete(entityId);
          logView(entityId, Date.now() - enteredAt, "card");
        }
      });
    },
    { threshold: 0.5 }
  );
  cards.forEach((card) => observer.observe(card));
}

async function loadFeed() {
  const res = await fetch("/api/feed?limit=100");
  feedEntities = await res.json();
  feedEl.innerHTML = feedEntities.map((e, i) => cardHtml(e, i)).join("");
  observeCards();
}

async function openDetail(id) {
  const res = await fetch(`/api/entity/${id}`);
  if (!res.ok) return;
  flushDetailView();
  const entity = await res.json();
  currentDetailEntity = entity;
  currentDetailTodoId = null;
  const index = feedEntities.findIndex((e) => e.id === id);
  detailContentEl.innerHTML = detailHtml(entity, index >= 0 ? index : 0);
  detailEl.classList.remove("hidden");
  detailViewEntityId = id;
  detailViewStart = Date.now();
  logInteraction(id, "open_detail");
}

function todoDetailHtml(todo) {
  const sourceLink = todo.source_entity_id
    ? `<a class="todo-source-link" data-open-entity="${todo.source_entity_id}" href="#">[ view in feed → ]</a>`
    : "";
  const comments = todo.comments || [];
  const commentsHtml = comments.length
    ? comments.map((c) => `
        <div class="comment-item">
          <div class="comment-meta">${escapeHtml(formatTs(c.created_at))}</div>
          <div class="comment-body">${escapeHtml(c.body)}</div>
        </div>`).join("")
    : '<p class="todo-empty">// no comments yet</p>';

  const entityBadge = todo.source_entity_type
    ? `<span class="type-tag" style="color: ${typeColor(todo.source_entity_type)}">[${escapeHtml(todo.source_entity_type)}]</span>`
    : "";

  return `
    <span class="section-tag ${escapeHtml(todo.status)}">${escapeHtml(todo.status)}</span>
    ${entityBadge}
    <h1>${escapeHtml(todo.title)}</h1>
    ${sourceLink}
    <div class="todo-controls" style="margin: 16px 0 24px;">
      <span>due:</span>
      <input type="date" class="due-input" value="${todo.due_date || ""}" data-todo-detail-due="${todo.id}" />
      <button class="bracket-btn todo-detail-done" data-id="${todo.id}" data-done="${todo.status === "done"}">[ ${todo.status === "done" ? "undo" : "done"} ]</button>
      <button class="bracket-btn todo-detail-delete" data-id="${todo.id}">[ delete ]</button>
    </div>
    <h2>comments</h2>
    <div class="comment-list">${commentsHtml}</div>
    <form id="todoCommentForm" class="quick-add" data-id="${todo.id}">
      <span class="quick-add-caret">&gt;</span>
      <input id="todoCommentInput" type="text" placeholder="add a comment…" autocomplete="off" />
      <button type="submit" class="bracket-btn small">[ + ]</button>
    </form>
  `;
}

async function openTodoDetail(id) {
  const res = await fetch(`/api/todos/${id}`);
  if (!res.ok) return;
  flushDetailView();
  const todo = await res.json();
  currentDetailEntity = null;
  currentDetailTodoId = id;
  detailContentEl.innerHTML = todoDetailHtml(todo);
  detailEl.classList.remove("hidden");
}

// ---- add-to-todo prompt (asks for an optional comment before saving) ----

const addTodoPromptEl = document.getElementById("addTodoPrompt");
const addTodoContextEl = document.getElementById("addTodoContext");
const addTodoCommentEl = document.getElementById("addTodoComment");

let pendingAddEntity = null;
let pendingAddTrigger = null;

function openAddTodoPrompt(entity, triggerEl) {
  pendingAddEntity = entity;
  pendingAddTrigger = triggerEl;
  addTodoContextEl.textContent = `add to todo: ${entity.one_liner || entity.title}`;
  addTodoCommentEl.value = "";
  addTodoPromptEl.classList.remove("hidden");
  addTodoCommentEl.focus();
}

function closeAddTodoPrompt() {
  pendingAddEntity = null;
  pendingAddTrigger = null;
  addTodoPromptEl.classList.add("hidden");
}

async function confirmAddTodo() {
  if (!pendingAddEntity) return;
  const entity = pendingAddEntity;
  const triggerEl = pendingAddTrigger;
  const comment = addTodoCommentEl.value.trim();

  const res = await fetch("/api/todos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: entity.one_liner || entity.title, source_entity_id: entity.id }),
  });
  const todo = await res.json();

  if (comment) {
    await fetch(`/api/todos/${todo.id}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: comment }),
    });
  }

  if (triggerEl) {
    triggerEl.classList.add("added");
    triggerEl.textContent = triggerEl.classList.contains("card-add-btn") ? "[ ✓ ]" : "[ added ✓ ]";
  }
  logInteraction(entity.id, "add_todo");
  closeAddTodoPrompt();
}

document.getElementById("addTodoSave").addEventListener("click", confirmAddTodo);
document.getElementById("addTodoCancel").addEventListener("click", closeAddTodoPrompt);
document.querySelector(".add-todo-backdrop").addEventListener("click", closeAddTodoPrompt);

feedEl.addEventListener("click", async (event) => {
  const addBtn = event.target.closest(".card-add-btn");
  if (addBtn) {
    event.stopPropagation();
    const res = await fetch(`/api/entity/${addBtn.dataset.addId}`);
    const entity = await res.json();
    openAddTodoPrompt(entity, addBtn);
    return;
  }
  const card = event.target.closest(".card");
  if (card) openDetail(card.dataset.id);
});

detailContentEl.addEventListener("click", async (event) => {
  if (event.target.id === "detailAddTodo" && currentDetailEntity) {
    openAddTodoPrompt(currentDetailEntity, event.target);
    return;
  }
  const sourceOpenLink = event.target.closest(".source-link");
  if (sourceOpenLink && currentDetailEntity) {
    logInteraction(currentDetailEntity.id, "open_source");
  }
  const doneBtn = event.target.closest(".todo-detail-done");
  if (doneBtn) {
    const isDone = doneBtn.dataset.done === "true";
    await fetch(`/api/todos/${doneBtn.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done: !isDone }),
    });
    openTodoDetail(doneBtn.dataset.id);
    loadTodos();
    return;
  }
  const deleteBtn = event.target.closest(".todo-detail-delete");
  if (deleteBtn) {
    await fetch(`/api/todos/${deleteBtn.dataset.id}`, { method: "DELETE" });
    detailEl.classList.add("hidden");
    loadTodos();
    return;
  }
  const sourceLink = event.target.closest("[data-open-entity]");
  if (sourceLink) {
    event.preventDefault();
    document.querySelector('.tab-btn[data-tab="feedScreen"]').click();
    openDetail(sourceLink.dataset.openEntity);
  }
});

detailContentEl.addEventListener("change", async (event) => {
  const dueInput = event.target.closest("[data-todo-detail-due]");
  if (dueInput) {
    const id = dueInput.dataset.todoDetailDue;
    await fetch(`/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ due_date: dueInput.value || null }),
    });
    openTodoDetail(id);
    loadTodos();
  }
});

detailContentEl.addEventListener("submit", async (event) => {
  if (event.target.id !== "todoCommentForm") return;
  event.preventDefault();
  const form = event.target;
  const input = document.getElementById("todoCommentInput");
  const text = input.value.trim();
  if (!text) return;
  await fetch(`/api/todos/${form.dataset.id}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body: text }),
  });
  openTodoDetail(form.dataset.id);
});

document.getElementById("closeDetail").addEventListener("click", () => {
  flushDetailView();
  detailEl.classList.add("hidden");
});

async function loadLog(date) {
  const res = await fetch(`/api/log/${date}`);
  const entities = await res.json();
  logListEl.innerHTML = entities.length
    ? entities.map((e) => `
        <div class="log-item" data-id="${e.id}">
          <div class="type" style="color:${typeColor(e.type)}">[${escapeHtml(e.type)}]</div>
          <div class="title">${escapeHtml(e.title)}</div>
        </div>`).join("")
    : "<p>No entries for this date.</p>";
}

document.getElementById("logToggle").addEventListener("click", () => {
  const today = new Date().toISOString().slice(0, 10);
  logDateEl.value = logDateEl.value || today;
  loadLog(logDateEl.value);
  logViewEl.classList.remove("hidden");
});

document.getElementById("closeLog").addEventListener("click", () => {
  logViewEl.classList.add("hidden");
});

logDateEl.addEventListener("change", () => loadLog(logDateEl.value));

logListEl.addEventListener("click", (event) => {
  const item = event.target.closest(".log-item");
  if (item) {
    logViewEl.classList.add("hidden");
    openDetail(item.dataset.id);
  }
});

// ---- tab bar ----

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab !== "feedScreen") flushOpenCardViews();
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "homeScreen") { loadTodos(); loadDrafts(); }
  });
});

// ---- home / todos ----

const addedListEl = document.getElementById("addedList");
const committedListEl = document.getElementById("committedList");
const doneListEl = document.getElementById("doneList");

function todoItemHtml(todo) {
  const overdue = todo.status === "committed" && todo.due_date && todo.due_date < new Date().toISOString().slice(0, 10);
  const sourceLink = todo.source_entity_id
    ? `<a class="todo-source-link" data-open-entity="${todo.source_entity_id}" href="#">[ from feed → ]</a>`
    : "";
  const entityBadge = todo.source_entity_type
    ? `<span class="type-tag small" style="color: ${typeColor(todo.source_entity_type)}">[${escapeHtml(todo.source_entity_type)}]</span>`
    : "";
  return `
    <div class="todo-item ${overdue ? "overdue" : ""}" data-id="${todo.id}">
      ${entityBadge}
      <button class="todo-title todo-title-btn" data-open-todo="${todo.id}">${escapeHtml(todo.title)}</button>
      ${sourceLink}
      <div class="todo-controls">
        <span>due:</span>
        <input type="date" class="due-input" value="${todo.due_date || ""}" data-id="${todo.id}" />
        <button class="done-btn" data-id="${todo.id}" data-done="${todo.status === "done"}">
          [ ${todo.status === "done" ? "undo" : "done"} ]
        </button>
        <button class="delete-btn" data-id="${todo.id}">[ delete ]</button>
      </div>
    </div>`;
}

// ---- drafts ----

const draftsListEl = document.getElementById("draftsList");

function draftItemHtml(draft) {
  return `
    <div class="draft-item" data-id="${draft.id}">
      <div class="draft-platform">[${escapeHtml(draft.platform)}]</div>
      <div class="draft-content">${escapeHtml(draft.content)}</div>
      <div class="todo-controls">
        <button class="draft-approve-btn" data-id="${draft.id}">[ approve ]</button>
        <button class="draft-reject-btn" data-id="${draft.id}">[ reject ]</button>
      </div>
    </div>`;
}

async function loadDrafts() {
  const res = await fetch("/api/drafts?status=pending");
  const drafts = await res.json();
  draftsListEl.innerHTML = drafts.length
    ? drafts.map(draftItemHtml).join("")
    : '<p class="todo-empty">// no drafts pending</p>';
}

document.getElementById("homeScreen").addEventListener("click", async (event) => {
  const approveBtn = event.target.closest(".draft-approve-btn");
  if (approveBtn) {
    await fetch(`/api/drafts/${approveBtn.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "approved" }),
    });
    loadDrafts();
    return;
  }
  const rejectBtn = event.target.closest(".draft-reject-btn");
  if (rejectBtn) {
    await fetch(`/api/drafts/${rejectBtn.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "rejected" }),
    });
    loadDrafts();
  }
});

async function loadTodos() {
  const [added, committed, done] = await Promise.all([
    fetch("/api/todos?status=added").then((r) => r.json()),
    fetch("/api/todos?status=committed").then((r) => r.json()),
    fetch("/api/todos?status=done").then((r) => r.json()),
  ]);
  addedListEl.innerHTML = added.length ? added.map(todoItemHtml).join("") : '<p class="todo-empty">// nothing added</p>';
  committedListEl.innerHTML = committed.length ? committed.map(todoItemHtml).join("") : '<p class="todo-empty">// nothing committed</p>';
  doneListEl.innerHTML = done.length ? done.map(todoItemHtml).join("") : '<p class="todo-empty">// nothing done yet</p>';
}

document.getElementById("quickAddForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("quickAddInput");
  const title = input.value.trim();
  if (!title) return;
  await fetch("/api/todos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  input.value = "";
  loadTodos();
});

document.getElementById("homeScreen").addEventListener("change", async (event) => {
  if (event.target.classList.contains("due-input")) {
    await fetch(`/api/todos/${event.target.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ due_date: event.target.value || null }),
    });
    loadTodos();
  }
});

document.getElementById("homeScreen").addEventListener("click", async (event) => {
  const openTodoBtn = event.target.closest("[data-open-todo]");
  if (openTodoBtn) {
    openTodoDetail(openTodoBtn.dataset.openTodo);
    return;
  }
  const doneBtn = event.target.closest(".done-btn");
  if (doneBtn) {
    const isDone = doneBtn.dataset.done === "true";
    await fetch(`/api/todos/${doneBtn.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done: !isDone }),
    });
    loadTodos();
    return;
  }
  const deleteBtn = event.target.closest(".delete-btn");
  if (deleteBtn) {
    await fetch(`/api/todos/${deleteBtn.dataset.id}`, { method: "DELETE" });
    loadTodos();
    return;
  }
  const sourceLink = event.target.closest("[data-open-entity]");
  if (sourceLink) {
    event.preventDefault();
    document.querySelector('.tab-btn[data-tab="feedScreen"]').click();
    openDetail(sourceLink.dataset.openEntity);
  }
});

document.getElementById("doneToggle").addEventListener("click", () => {
  doneListEl.classList.toggle("hidden");
});

// ---- weekly summary ----

const summaryResultEl = document.getElementById("summaryResult");
const pastSummariesListEl = document.getElementById("pastSummariesList");

function summaryItemHtml(s) {
  return `<div class="summary-item"><div class="summary-meta">${escapeHtml(s.period_start)} → ${escapeHtml(s.period_end)}</div>${escapeHtml(s.summary)}</div>`;
}

async function loadPastSummaries() {
  const res = await fetch("/api/weekly-summary");
  const rows = await res.json();
  pastSummariesListEl.innerHTML = rows.length
    ? rows.map(summaryItemHtml).join("")
    : '<p class="todo-empty">// no summaries yet</p>';
}

document.getElementById("weeklySummaryBtn").addEventListener("click", async () => {
  const btn = document.getElementById("weeklySummaryBtn");
  btn.disabled = true;
  btn.textContent = "[ generating… ]";
  summaryResultEl.classList.remove("hidden");
  summaryResultEl.textContent = "// thinking…";
  try {
    const res = await fetch("/api/weekly-summary", { method: "POST" });
    const row = await res.json();
    summaryResultEl.textContent = row.summary || row.error || "// no summary generated";
    loadPastSummaries();
  } catch (err) {
    summaryResultEl.textContent = "// failed to generate summary";
  } finally {
    btn.disabled = false;
    btn.textContent = "[ weekly summary ]";
  }
});

document.getElementById("pastSummariesToggle").addEventListener("click", () => {
  pastSummariesListEl.classList.toggle("hidden");
  if (!pastSummariesListEl.classList.contains("hidden")) loadPastSummaries();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/app/sw.js").catch(() => {});
}

loadFeed();
loadTodos();
loadDrafts();
