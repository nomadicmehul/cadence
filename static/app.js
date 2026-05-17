// Cadence — frontend logic
// =========================================

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  tab: "dashboard",
  pillars: [],
  ideas: [],
  drafts: [],
  voice: [],
  engagement: [],
  analytics: [],
  topics: [],
  topicSources: [],
  selectedDraftId: null,
  calendarCursor: new Date(),
};

// ---------- API ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail;
    try { detail = await res.json(); } catch { detail = await res.text(); }
    throw new Error(detail.error || detail.message || res.statusText);
  }
  return res.headers.get("content-type")?.includes("json")
    ? res.json()
    : res.text();
}

// ---------- Toast ----------
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// ---------- Modal ----------
function openModal(title, html, opts = {}) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = "";
  if (typeof html === "string") $("#modal-body").innerHTML = html;
  else $("#modal-body").appendChild(html);
  const m = $("#modal").querySelector(".modal");
  m.classList.toggle("wide", !!opts.wide);
  $("#modal").hidden = false;
}
function closeModal() {
  $("#modal").hidden = true;
  const m = $("#modal").querySelector(".modal");
  if (m) m.classList.remove("wide");
}
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});

// ---------- Helpers ----------
const fmtDateTime = (s) => {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
};
const fmtDate = (d) => d.toLocaleDateString(undefined, {
  month: "short", day: "numeric", year: "numeric"
});
const escape = (s) => (s || "").replace(/[&<>"']/g, (m) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[m]));
const truncate = (s, n) => (s || "").length > n ? (s.slice(0, n - 1) + "…") : (s || "");

function withSpinner(btn, fn) {
  return async (...args) => {
    if (!btn) return fn(...args);
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> ' + orig;
    try { return await fn(...args); }
    finally { btn.disabled = false; btn.innerHTML = orig; }
  };
}

// ---------- Tabs ----------
$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  switchTab(btn.dataset.tab);
});

function switchTab(tab) {
  state.tab = tab;
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + tab));
  if (tab === "dashboard") loadDashboard();
  if (tab === "topics") loadTopics();
  if (tab === "ideas") loadIdeas();
  if (tab === "drafts") loadDrafts();
  if (tab === "calendar") renderCalendar();
  if (tab === "analytics") loadAnalytics();
  if (tab === "engagement") loadEngagement();
  if (tab === "voice") loadVoice();
  if (tab === "settings") loadSettings();
}

// =====================================================================
// DASHBOARD
// =====================================================================
async function loadDashboard() {
  try {
    const d = await api("/api/dashboard");
    $("#stat-row").innerHTML = `
      <div class="stat"><div class="stat-label">Raw ideas</div>
        <div class="stat-value">${d.counts.ideas_raw}</div>
        <div class="stat-sub">Sitting in the bank</div></div>
      <div class="stat"><div class="stat-label">In drafts</div>
        <div class="stat-value">${d.counts.drafts}</div>
        <div class="stat-sub">Draft + Ready</div></div>
      <div class="stat"><div class="stat-label">Scheduled</div>
        <div class="stat-value">${d.counts.scheduled}</div>
        <div class="stat-sub">Queued for posting</div></div>
      <div class="stat"><div class="stat-label">Published</div>
        <div class="stat-value">${d.counts.published}</div>
        <div class="stat-sub">All-time</div></div>`;
    $("#next-up").innerHTML = d.next_up.length
      ? d.next_up.map(p => `
        <div class="up-item">
          <div class="pill" style="background:${p.pillar_color || 'var(--accent)'}"></div>
          <div class="when">${fmtDateTime(p.scheduled_for)}</div>
          <div class="title">${escape(p.title || 'Untitled')}</div>
          <span class="status-chip scheduled">Scheduled</span>
        </div>`).join("")
      : `<div class="muted">Nothing scheduled. Hit <b>Auto-schedule queue</b>.</div>`;
    const max = Math.max(1, ...d.pillar_mix.map(p => p.n));
    $("#pillar-mix").innerHTML = d.pillar_mix.length
      ? d.pillar_mix.map(p => `
        <div class="pillar-bar">
          <div class="top"><span>${escape(p.name)}</span><span class="muted">${p.n}</span></div>
          <div class="track"><div class="fill"
            style="width:${(p.n / max * 100).toFixed(0)}%; background:${p.color}"></div></div>
        </div>`).join("")
      : `<div class="muted">No published posts yet.</div>`;
    $("#totals").innerHTML = `
      <div class="row" style="grid-template-columns: 1fr 1fr; margin: 0; gap:8px;">
        <div class="an-card" style="padding:10px"><div class="muted tiny">Impressions</div>
          <div style="font-size:22px;font-weight:600">${d.totals.i.toLocaleString()}</div></div>
        <div class="an-card" style="padding:10px"><div class="muted tiny">Likes</div>
          <div style="font-size:22px;font-weight:600">${d.totals.l.toLocaleString()}</div></div>
        <div class="an-card" style="padding:10px"><div class="muted tiny">Comments</div>
          <div style="font-size:22px;font-weight:600">${d.totals.c.toLocaleString()}</div></div>
        <div class="an-card" style="padding:10px"><div class="muted tiny">Followers gained</div>
          <div style="font-size:22px;font-weight:600">${d.totals.f.toLocaleString()}</div></div>
      </div>`;

    await loadReflectionCard();
    await loadMemorySnapshot();
  } catch (e) { toast("Could not load dashboard: " + e.message, "error"); }
}

async function loadReflectionCard() {
  const target = $("#reflection-card");
  if (!target) return;
  try {
    const list = await api("/api/brain/reflections?limit=1");
    const latest = list[0];
    if (!latest) {
      target.innerHTML = `
        <div class="memory-empty">
          No reflection yet. Hit <b>Run reflection now</b> to have Claude read
          your last week and drop 3 fresh ideas into the bank.
        </div>`;
      return;
    }
    const sig = latest.signals || {};
    const sigChips = [
      sig.best_pillar ? `<span class="status-chip ready">winner pillar: ${escape(sig.best_pillar)}</span>` : "",
      sig.best_format ? `<span class="status-chip ready">winner format: ${escape(sig.best_format)}</span>` : "",
      sig.weakest_pillar ? `<span class="status-chip">lagging: ${escape(sig.weakest_pillar)}</span>` : "",
    ].filter(Boolean).join(" ");
    const topics = Array.isArray(sig.topics_to_double_down_on)
      ? sig.topics_to_double_down_on.filter(Boolean).slice(0, 5)
      : [];
    const topicsHtml = topics.length
      ? `<div class="muted tiny" style="margin-top:8px">Double down: ${topics.map(t => `<code>${escape(t)}</code>`).join(" · ")}</div>`
      : "";
    const ideasN = (latest.ideas_created || []).length;
    target.innerHTML = `
      <div class="muted tiny" style="margin-bottom:6px">
        ${fmtDateTime(latest.created_at)} · ${latest.window_days}-day window
        ${ideasN ? ` · dropped ${ideasN} idea${ideasN === 1 ? "" : "s"} into the bank` : ""}
      </div>
      <div style="white-space:pre-wrap;line-height:1.55">${escape(latest.summary || "")}</div>
      ${sigChips ? `<div style="margin-top:10px">${sigChips}</div>` : ""}
      ${topicsHtml}
      ${ideasN ? `<button class="btn sm" id="reflection-jump-ideas" style="margin-top:10px">See ideas in Ideas Bank</button>` : ""}`;
    const jump = $("#reflection-jump-ideas");
    if (jump) jump.addEventListener("click", () => switchTab("ideas"));
  } catch (e) {
    target.innerHTML = `<div class="memory-empty">Couldn't load reflection: ${escape(e.message)}</div>`;
  }
}

async function runReflection() {
  const btn = $("#reflect-now");
  toast("Reflecting on the last 7 days… ~15s", "");
  await withSpinner(btn, async () => {
    const r = await api("/api/brain/reflect", { method: "POST", body: { window_days: 7 } });
    if (!r.ok) {
      toast("Reflection failed: " + (r.error || "unknown"), "error");
      return;
    }
    const n = (r.ideas_created || []).length;
    toast(`Reflection saved. ${n} fresh idea${n === 1 ? "" : "s"} added.`, "ok");
    await loadReflectionCard();
    await loadMemorySnapshot();
  })();
}

async function loadMemorySnapshot() {
  const target = $("#memory-snapshot");
  if (!target) return;
  try {
    const m = await api("/api/memory");
    const winners = (m.top_performers || []).map(w => `
      <div class="memory-winner">
        <span class="score">${w.score}</span>
        <span style="flex:1">${escape(w.title || "Untitled")}</span>
        <span class="muted tiny">${escape(w.format)} · ${escape(w.pillar || "—")}</span>
        <button class="btn sm" data-repurpose="${w.id}">Repurpose</button>
      </div>`).join("");
    target.innerHTML = `
      <div class="memory-stats">
        <div class="memory-stat">
          <div class="lbl">Voice samples</div>
          <div class="val">${m.voice_samples}</div>
          <div class="sub">3 sampled into every prompt</div>
        </div>
        <div class="memory-stat">
          <div class="lbl">Published posts</div>
          <div class="val">${m.published}</div>
          <div class="sub">Top 3 (by engagement) shown to AI as winners</div>
        </div>
        <div class="memory-stat">
          <div class="lbl">Discarded ideas</div>
          <div class="val">${m.discarded}</div>
          <div class="sub">Patterns the AI now avoids</div>
        </div>
      </div>
      ${winners
        ? `<div class="memory-winners">${winners}</div>`
        : `<div class="memory-empty">
             No published posts logged yet. Once you log analytics for a post,
             top performers feed back into every generation as a positive example.
           </div>`}`;
    target.querySelectorAll("[data-repurpose]").forEach(b => {
      b.addEventListener("click", () => repurposeDraft(+b.dataset.repurpose));
    });
  } catch (e) {
    target.innerHTML = `<div class="memory-empty">Couldn't load memory: ${escape(e.message)}</div>`;
  }
}

async function repurposeDraft(id) {
  if (!confirm("Generate 3 fresh format variants of this winner?")) return;
  toast("Repurposing… this takes ~10s", "");
  try {
    const r = await api(`/api/drafts/${id}/repurpose`, { method: "POST" });
    if (!r.ok) return toast(r.error || "Failed", "error");
    toast(`Created ${r.count} variants in Drafts`, "ok");
    switchTab("drafts");
    state.selectedDraftId = r.created[0];
    await loadDrafts();
  } catch (e) {
    toast("Repurpose failed: " + e.message, "error");
  }
}

// Quick actions
document.querySelector("#view-dashboard").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-jump]");
  if (!btn) return;
  switchTab(btn.dataset.jump);
  setTimeout(() => {
    if (btn.dataset.action === "generate") openIdeaGenerator();
    if (btn.dataset.action === "new") openDraftEditor(null);
    if (btn.dataset.action === "autoschedule") autoSchedule();
    if (btn.dataset.action === "insights") runInsights();
  }, 50);
});

$("#reflect-now")?.addEventListener("click", runReflection);

// =====================================================================
// PILLARS (used everywhere)
// =====================================================================
async function loadPillars() {
  state.pillars = await api("/api/pillars");
  // populate filter dropdowns
  const opts = state.pillars.map(p =>
    `<option value="${p.id}">${escape(p.name)}</option>`).join("");
  const ipf = $("#idea-pillar-filter");
  ipf.innerHTML = `<option value="">All pillars</option>` + opts;
}

// =====================================================================
// TOPICS (RSS intake)
// =====================================================================
async function loadTopics() {
  await loadPillars();
  await loadTopicSources();
  renderTopicSources();
  populateTopicSourceFilter();
  await refreshTopicsList();
}

async function loadTopicSources() {
  state.topicSources = await api("/api/topics/sources");
}

function populateTopicSourceFilter() {
  const sel = $("#topic-source-filter");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = `<option value="">All sources</option>` +
    state.topicSources.map(s =>
      `<option value="${s.id}">${escape(s.name)}</option>`
    ).join("");
  sel.value = cur;
}

function renderTopicSources() {
  const list = $("#topic-sources-list");
  if (!list) return;
  if (!state.topicSources.length) {
    list.innerHTML = `<div class="muted" style="padding:8px">
      No sources yet. Click <b>+ Add source</b>.</div>`;
    return;
  }
  list.innerHTML = state.topicSources.map(s => {
    const lastBadge = s.last_status
      ? `<span class="muted tiny" title="${escape(s.last_fetched_at || '')}">${escape(s.last_status)}</span>`
      : "";
    return `
      <div class="src-row" data-id="${s.id}">
        <label class="toggle">
          <input type="checkbox" data-act="toggle" ${s.enabled ? "checked" : ""} />
          <span>${escape(s.name)}</span>
        </label>
        <code class="muted tiny" style="flex:1;overflow:hidden;text-overflow:ellipsis">${escape(s.url)}</code>
        ${lastBadge}
        <button class="btn sm" data-act="edit">Edit</button>
        <button class="btn sm danger" data-act="delete">×</button>
      </div>`;
  }).join("");
}

$("#topic-sources-list")?.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const row = btn.closest(".src-row");
  const id = +row.dataset.id;
  const src = state.topicSources.find(s => s.id === id);
  if (!src) return;
  const act = btn.dataset.act;
  if (act === "toggle") {
    await api(`/api/topics/sources/${id}`, {
      method: "PUT",
      body: { enabled: btn.checked ? 1 : 0 },
    });
    await loadTopicSources();
    renderTopicSources();
    return;
  }
  if (act === "edit") return openTopicSourceEditor(src);
  if (act === "delete") {
    if (!confirm(`Remove source "${src.name}"? Existing topics from it are kept.`)) return;
    await api(`/api/topics/sources/${id}`, { method: "DELETE" });
    await loadTopicSources();
    renderTopicSources();
    populateTopicSourceFilter();
  }
});

function openTopicSourceEditor(src) {
  const isNew = !src;
  const html = `
    <label>Name<input id="m-name" value="${escape(src?.name || "")}" /></label>
    <label>Feed URL<input id="m-url" value="${escape(src?.url || "")}" placeholder="https://example.com/rss" /></label>
    <label>Kind
      <select id="m-kind">
        <option value="rss" ${src?.kind === 'rss' ? 'selected' : ''}>RSS</option>
        <option value="atom" ${src?.kind === 'atom' ? 'selected' : ''}>Atom</option>
      </select>
    </label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="m-save">${isNew ? "Add source" : "Save"}</button>
      <button class="btn" id="m-cancel">Cancel</button>
    </div>`;
  openModal(isNew ? "Add topic source" : "Edit topic source", html);
  $("#m-cancel").onclick = closeModal;
  $("#m-save").onclick = async () => {
    const body = {
      name: $("#m-name").value.trim(),
      url: $("#m-url").value.trim(),
      kind: $("#m-kind").value,
    };
    if (!body.name || !body.url) return toast("Name and URL required", "error");
    try {
      if (isNew) await api("/api/topics/sources", { method: "POST", body });
      else await api(`/api/topics/sources/${src.id}`, { method: "PUT", body });
    } catch (e) {
      return toast("Save failed: " + e.message, "error");
    }
    closeModal();
    await loadTopicSources();
    renderTopicSources();
    populateTopicSourceFilter();
  };
}

async function refreshTopicsList() {
  const status = $("#topic-status-filter").value;
  const sourceId = $("#topic-source-filter").value;
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (sourceId) params.set("source_id", sourceId);
  state.topics = await api("/api/topics" + (params.toString() ? "?" + params : ""));
  renderTopicsList();
}

function renderTopicsList() {
  const list = $("#topics-list");
  if (!list) return;
  if (!state.topics.length) {
    list.innerHTML = `<div class="muted" style="grid-column:1/-1;padding:30px;text-align:center">
      No topics here. Hit <b>Fetch now</b> to pull from your sources.</div>`;
    return;
  }
  list.innerHTML = state.topics.map(t => {
    const summary = truncate(t.summary || "", 280);
    const when = t.published_at || t.ingested_at;
    const sourceTag = t.source_name
      ? `<span class="muted tiny">${escape(t.source_name)}</span>` : "";
    const pillarTag = t.pillar_name
      ? `<span class="pillar-tag"><span class="swatch" style="background:${t.pillar_color || '#666'}"></span>${escape(t.pillar_name)}</span>`
      : "";
    const statusChip = `<span class="status-chip ${t.status}">${t.status}</span>`;
    const linkBtn = t.url
      ? `<a class="btn sm ghost" href="${escape(t.url)}" target="_blank" rel="noopener">Open ↗</a>` : "";
    const isUsable = t.status === "new" || t.status === "queued";
    const draftBtn = isUsable
      ? `<button class="btn primary sm" data-act="draft" data-id="${t.id}">Draft an angle</button>` : "";
    const dismissBtn = isUsable
      ? `<button class="btn sm" data-act="dismiss" data-id="${t.id}">Dismiss</button>` : "";
    const restoreBtn = (t.status === "dismissed" || t.status === "used")
      ? `<button class="btn sm" data-act="restore" data-id="${t.id}">Restore</button>` : "";
    return `
      <div class="idea topic" data-id="${t.id}">
        <div class="pillar-tag">
          ${sourceTag}
          ${pillarTag}
          <span style="margin-left:auto">${statusChip}</span>
        </div>
        <div class="title">${escape(t.title)}</div>
        ${summary ? `<div class="angle">${escape(summary)}</div>` : ""}
        <div class="muted tiny">${fmtDateTime(when)}</div>
        <div class="actions">
          ${draftBtn}
          ${linkBtn}
          ${dismissBtn}
          ${restoreBtn}
        </div>
      </div>`;
  }).join("");
}

$("#topics-list")?.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = +btn.dataset.id;
  const act = btn.dataset.act;
  if (act === "dismiss") {
    await api(`/api/topics/${id}`, { method: "PUT", body: { status: "dismissed" } });
    return refreshTopicsList();
  }
  if (act === "restore") {
    await api(`/api/topics/${id}`, { method: "PUT", body: { status: "new" } });
    return refreshTopicsList();
  }
  if (act === "draft") {
    return withSpinner(btn, async () => {
      toast("Asking Claude for an angle…", "");
      try {
        const r = await api(`/api/topics/${id}/draft`, { method: "POST", body: {} });
        if (!r.ok) throw new Error(r.error);
        toast("Idea added to Ideas Bank", "ok");
        await refreshTopicsList();
      } catch (e) {
        toast("Draft failed: " + e.message, "error");
      }
    })();
  }
});

$("#topic-status-filter")?.addEventListener("change", refreshTopicsList);
$("#topic-source-filter")?.addEventListener("change", refreshTopicsList);
$("#topics-add-source")?.addEventListener("click", () => openTopicSourceEditor(null));
$("#topics-fetch")?.addEventListener("click", async () => {
  const btn = $("#topics-fetch");
  await withSpinner(btn, async () => {
    toast("Fetching feeds…", "");
    try {
      const r = await api("/api/topics/fetch", { method: "POST", body: {} });
      if (!r.ok) throw new Error(r.error);
      const errors = (r.per_source || []).filter(s => s.error);
      if (errors.length) {
        toast(`Fetched ${r.inserted_total} new · ${errors.length} source(s) failed`, "error");
      } else {
        toast(`Fetched ${r.inserted_total} new from ${r.sources_checked} source(s)`, "ok");
      }
      await loadTopicSources();
      renderTopicSources();
      await refreshTopicsList();
    } catch (e) {
      toast("Fetch failed: " + e.message, "error");
    }
  })();
});

// =====================================================================
// IDEAS
// =====================================================================
async function loadIdeas() {
  await loadPillars();
  const status = $("#idea-status-filter").value;
  const pillar = $("#idea-pillar-filter").value;
  const ideas = await api("/api/ideas" + (status ? `?status=${status}` : ""));
  state.ideas = pillar ? ideas.filter(i => String(i.pillar_id) === pillar) : ideas;
  renderIdeas();
}

function renderIdeas() {
  const list = $("#ideas-list");
  if (!state.ideas.length) {
    list.innerHTML = `<div class="muted" style="grid-column:1/-1;padding:30px;text-align:center">
      No ideas yet. Click <b>+ Generate with Claude</b>.</div>`;
    return;
  }
  list.innerHTML = state.ideas.map(i => `
    <div class="idea" data-id="${i.id}">
      <div class="pillar-tag">
        <span class="swatch" style="background:${i.pillar_color || '#666'}"></span>
        ${escape(i.pillar_name || 'Unassigned')}
        <span style="margin-left:auto"><span class="status-chip ${i.status}">${i.status}</span></span>
      </div>
      <div class="title">${escape(i.title)}</div>
      ${i.hook ? `<div class="hook">${escape(i.hook)}</div>` : ""}
      ${i.angle ? `<div class="angle">${escape(i.angle)}</div>` : ""}
      <div class="actions">
        <button class="btn primary sm" data-act="draft" data-id="${i.id}">Draft with Claude</button>
        <button class="btn sm" data-act="edit" data-id="${i.id}">Edit</button>
        <button class="btn sm danger" data-act="delete" data-id="${i.id}">×</button>
      </div>
    </div>`).join("");
}

$("#ideas-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = +btn.dataset.id;
  const idea = state.ideas.find(i => i.id === id);
  if (btn.dataset.act === "delete") {
    if (!confirm("Delete this idea?")) return;
    await api(`/api/ideas/${id}`, { method: "DELETE" });
    return loadIdeas();
  }
  if (btn.dataset.act === "edit") return openIdeaEditor(idea);
  if (btn.dataset.act === "draft") {
    return withSpinner(btn, async () => {
      const fmtMatch = (idea.angle || "").match(/\[format:\s*(\w+)\]/);
      const fmt = fmtMatch ? fmtMatch[1] : "story";
      const res = await api("/api/drafts/generate", {
        method: "POST",
        body: { idea_id: id, format: fmt },
      });
      if (!res.ok) throw new Error(res.error);
      toast("Draft created", "ok");
      switchTab("drafts");
      state.selectedDraftId = res.id;
      await loadDrafts();
    })();
  }
});

$("#idea-status-filter").addEventListener("change", loadIdeas);
$("#idea-pillar-filter").addEventListener("change", loadIdeas);
$("#idea-add").addEventListener("click", () => openIdeaEditor(null));
$("#idea-generate").addEventListener("click", openIdeaGenerator);

function openIdeaEditor(idea) {
  const isNew = !idea;
  const html = `
    <label>Pillar
      <select id="m-pillar">
        ${state.pillars.map(p => `<option value="${p.id}" ${idea && idea.pillar_id === p.id ? "selected" : ""}>${escape(p.name)}</option>`).join("")}
      </select>
    </label>
    <label>Title<input id="m-title" value="${escape(idea?.title || "")}"/></label>
    <label>Hook (first line)<textarea id="m-hook" rows="2">${escape(idea?.hook || "")}</textarea></label>
    <label>Angle / notes<textarea id="m-angle" rows="3">${escape(idea?.angle || "")}</textarea></label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="m-save">${isNew ? "Add idea" : "Save"}</button>
      <button class="btn" id="m-cancel">Cancel</button>
    </div>`;
  openModal(isNew ? "New idea" : "Edit idea", html);
  $("#m-cancel").onclick = closeModal;
  $("#m-save").onclick = async () => {
    const body = {
      pillar_id: +$("#m-pillar").value || null,
      title: $("#m-title").value.trim(),
      hook: $("#m-hook").value.trim(),
      angle: $("#m-angle").value.trim(),
      source: "manual",
    };
    if (!body.title) return toast("Title required", "error");
    if (isNew) await api("/api/ideas", { method: "POST", body });
    else await api(`/api/ideas/${idea.id}`, { method: "PUT", body });
    closeModal();
    loadIdeas();
  };
}

function openIdeaGenerator() {
  const html = `
    <label>Pillar (optional)
      <select id="g-pillar">
        <option value="">Any / mix</option>
        ${state.pillars.map(p => `<option value="${p.id}">${escape(p.name)}</option>`).join("")}
      </select>
    </label>
    <label>Theme or trigger (optional)
      <input id="g-theme" placeholder="e.g. 'platform engineering trends', 'I just spoke at KubeCon', a tweet you saw…"/>
    </label>
    <label>How many?<input id="g-count" type="number" value="5" min="1" max="12"/></label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="g-go">Generate ${'✨'}</button>
      <button class="btn" id="g-cancel">Cancel</button>
    </div>
    <p class="muted tiny" style="margin-top:14px">
      Claude will use your creator profile, voice samples, and recent ideas to avoid repeats.
    </p>`;
  openModal("Generate ideas with Claude", html);
  $("#g-cancel").onclick = closeModal;
  const goBtn = $("#g-go");
  goBtn.onclick = withSpinner(goBtn, async () => {
    const body = {
      pillar_id: +$("#g-pillar").value || null,
      theme: $("#g-theme").value.trim(),
      count: +$("#g-count").value || 5,
    };
    const res = await api("/api/ideas/generate", { method: "POST", body });
    if (!res.ok) return toast(res.error || "Generation failed", "error");
    closeModal();
    toast(`Added ${res.count} ideas`, "ok");
    loadIdeas();
  });
}

// =====================================================================
// DRAFTS
// =====================================================================
async function loadDrafts() {
  await loadPillars();
  const status = $("#draft-status-filter").value;
  state.drafts = await api("/api/drafts" + (status ? `?status=${status}` : ""));
  renderDraftsList();
  if (state.selectedDraftId && state.drafts.find(d => d.id === state.selectedDraftId)) {
    openDraftEditor(state.selectedDraftId);
  } else if (state.drafts.length && !state.selectedDraftId) {
    // leave editor as empty
  }
}
$("#draft-status-filter").addEventListener("change", loadDrafts);
$("#draft-new").addEventListener("click", () => openDraftEditor(null));

function renderDraftsList() {
  const list = $("#drafts-list");
  if (!state.drafts.length) {
    list.innerHTML = `<div class="muted" style="padding:18px;text-align:center">
      No drafts yet.</div>`;
    return;
  }
  list.innerHTML = state.drafts.map(d => `
    <div class="draft-row ${state.selectedDraftId === d.id ? "active" : ""}" data-id="${d.id}">
      <div class="top">
        <div class="title">${escape(d.title || truncate(d.body || "", 40) || "Untitled")}</div>
        <span class="status-chip ${d.status}">${d.status}</span>
      </div>
      <div class="meta">${escape(d.pillar_name || "—")} · ${d.format} · ${fmtDateTime(d.updated_at)}</div>
    </div>`).join("");
  list.querySelectorAll(".draft-row").forEach(r => {
    r.addEventListener("click", () => openDraftEditor(+r.dataset.id));
  });
}

function openDraftEditor(id) {
  if (id === null) {
    // brand new
    return promptNewDraft();
  }
  const d = state.drafts.find(x => x.id === id);
  if (!d) return;
  state.selectedDraftId = id;
  renderDraftsList();
  $("#draft-editor").classList.remove("empty");
  const scoreChip = (label, v) => `<span class="score">${label}: <b>${v ?? "—"}</b>/10</span>`;
  $("#draft-editor").innerHTML = `
    <div class="ed-row">
      <input id="ed-title" placeholder="Title" value="${escape(d.title || "")}" />
      <select id="ed-pillar">
        <option value="">Pillar…</option>
        ${state.pillars.map(p => `<option value="${p.id}" ${p.id === d.pillar_id ? "selected" : ""}>${escape(p.name)}</option>`).join("")}
      </select>
      <select id="ed-format">
        ${["story","list","contrarian","tutorial","bts","carousel"].map(f =>
          `<option value="${f}" ${f === d.format ? "selected" : ""}>${f}</option>`).join("")}
      </select>
      <select id="ed-status">
        ${["draft","ready","scheduled","published"].map(s =>
          `<option value="${s}" ${s === d.status ? "selected" : ""}>${s}</option>`).join("")}
      </select>
    </div>
    <textarea id="ed-body" class="body" placeholder="Write or paste here. Or click 'Generate'.">${escape(d.body || "")}</textarea>
    <div class="meta-bar">
      ${scoreChip("Hook", d.hook_score)} ${scoreChip("Voice", d.voice_score)}
      ${d.score_notes ? `<span class="muted tiny">${escape(d.score_notes)}</span>` : ""}
    </div>
    <div class="ed-row">
      <button class="btn" id="ed-save">Save</button>
      <button class="btn" id="ed-copy">Copy to clipboard</button>
      <button class="btn" id="ed-rewrite">Rewrite ${'✨'}</button>
      <button class="btn" id="ed-score">Score post</button>
      <button class="btn" id="ed-schedule">Schedule…</button>
      <button class="btn danger" id="ed-delete" style="margin-left:auto">Delete</button>
    </div>`;
  $("#ed-save").onclick = saveCurrentDraft;
  $("#ed-copy").onclick = () => {
    navigator.clipboard.writeText($("#ed-body").value).then(() =>
      toast("Copied. Paste it into LinkedIn.", "ok"));
  };
  $("#ed-rewrite").onclick = withSpinner($("#ed-rewrite"), async () => {
    const ins = prompt("Rewrite instruction (e.g. 'tighter, more contrarian', 'add a story')",
      "Tighter, more punchy, sharper hook.");
    if (!ins) return;
    await saveCurrentDraft();
    const r = await api(`/api/drafts/${id}/rewrite`, { method: "POST", body: { instruction: ins } });
    if (!r.ok) return toast(r.error, "error");
    $("#ed-body").value = r.body;
    toast("Rewritten", "ok");
  });
  $("#ed-score").onclick = withSpinner($("#ed-score"), async () => {
    await saveCurrentDraft();
    const r = await api(`/api/drafts/${id}/score`, { method: "POST" });
    if (!r.ok) return toast(r.error, "error");
    toast(`Hook ${r.hook_score}/10 · Voice ${r.voice_score}/10`, "ok");
    await loadDrafts();
  });
  $("#ed-schedule").onclick = () => openScheduleDialog(d);
  $("#ed-delete").onclick = async () => {
    if (!confirm("Delete this draft?")) return;
    await api(`/api/drafts/${id}`, { method: "DELETE" });
    state.selectedDraftId = null;
    $("#draft-editor").classList.add("empty");
    $("#draft-editor").innerHTML = `<div class="empty-state">Select a draft on the left.</div>`;
    loadDrafts();
  };
}

async function saveCurrentDraft() {
  const id = state.selectedDraftId;
  if (!id) return;
  const body = {
    title: $("#ed-title").value.trim(),
    pillar_id: +$("#ed-pillar").value || null,
    format: $("#ed-format").value,
    status: $("#ed-status").value,
    body: $("#ed-body").value,
  };
  await api(`/api/drafts/${id}`, { method: "PUT", body });
  toast("Saved", "ok");
  await loadDrafts();
}

function promptNewDraft() {
  const html = `
    <label>Title<input id="n-title" /></label>
    <label>Pillar
      <select id="n-pillar">
        <option value="">—</option>
        ${state.pillars.map(p => `<option value="${p.id}">${escape(p.name)}</option>`).join("")}
      </select>
    </label>
    <label>Format
      <select id="n-format">
        ${["story","list","contrarian","tutorial","bts","carousel"].map(f =>
          `<option value="${f}">${f}</option>`).join("")}
      </select>
    </label>
    <label>Brief / what's the post about? (optional — skip for blank canvas)
      <textarea id="n-brief" rows="4" placeholder="A wild story from KubeCon. The lesson is: pick boring tech."></textarea>
    </label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn" id="n-blank">Blank draft</button>
      <button class="btn primary" id="n-gen">Generate with Claude ${'✨'}</button>
    </div>`;
  openModal("New draft", html);
  $("#n-blank").onclick = async () => {
    const r = await api("/api/drafts", {
      method: "POST",
      body: {
        title: $("#n-title").value.trim() || "Untitled",
        pillar_id: +$("#n-pillar").value || null,
        format: $("#n-format").value,
        body: "",
      },
    });
    closeModal();
    state.selectedDraftId = r.id;
    await loadDrafts();
  };
  const genBtn = $("#n-gen");
  genBtn.onclick = withSpinner(genBtn, async () => {
    const r = await api("/api/drafts/generate", {
      method: "POST",
      body: {
        title: $("#n-title").value.trim(),
        pillar_id: +$("#n-pillar").value || null,
        format: $("#n-format").value,
        brief: $("#n-brief").value.trim() || "Open brief. Surprise me.",
      },
    });
    if (!r.ok) return toast(r.error || "Failed", "error");
    closeModal();
    toast("Draft generated", "ok");
    state.selectedDraftId = r.id;
    await loadDrafts();
  });
}

function openScheduleDialog(d) {
  const dt = d.scheduled_for ? new Date(d.scheduled_for) : new Date(Date.now() + 86400000);
  const local = (n) => String(n).padStart(2, "0");
  const isoLocal = `${dt.getFullYear()}-${local(dt.getMonth() + 1)}-${local(dt.getDate())}T${local(dt.getHours())}:${local(dt.getMinutes())}`;
  const html = `
    <label>When to post?<input type="datetime-local" id="s-when" value="${isoLocal}"/></label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="s-save">Schedule</button>
      <button class="btn" id="s-clear">Unschedule</button>
      <button class="btn" id="s-cancel">Cancel</button>
    </div>`;
  openModal("Schedule post", html);
  $("#s-cancel").onclick = closeModal;
  $("#s-save").onclick = async () => {
    const w = $("#s-when").value;
    if (!w) return;
    await api(`/api/drafts/${d.id}`, {
      method: "PUT", body: { scheduled_for: w, status: "scheduled" },
    });
    closeModal();
    toast("Scheduled", "ok");
    loadDrafts();
  };
  $("#s-clear").onclick = async () => {
    await api(`/api/drafts/${d.id}`, {
      method: "PUT", body: { scheduled_for: null, status: "ready" },
    });
    closeModal();
    loadDrafts();
  };
}

async function autoSchedule() {
  const days = +(prompt("Schedule across the next how many days?", "14") || 14);
  const r = await api("/api/calendar/auto-schedule", { method: "POST", body: { days } });
  toast(r.message || `Scheduled ${r.scheduled} drafts`, r.scheduled ? "ok" : "");
  if (state.tab === "calendar") renderCalendar();
  if (state.tab === "drafts") loadDrafts();
  if (state.tab === "dashboard") loadDashboard();
}

// =====================================================================
// CALENDAR
// =====================================================================
$("#cal-prev").addEventListener("click", () => {
  state.calendarCursor.setMonth(state.calendarCursor.getMonth() - 1);
  renderCalendar();
});
$("#cal-next").addEventListener("click", () => {
  state.calendarCursor.setMonth(state.calendarCursor.getMonth() + 1);
  renderCalendar();
});
$("#cal-auto").addEventListener("click", autoSchedule);

async function renderCalendar() {
  const c = state.calendarCursor;
  const first = new Date(c.getFullYear(), c.getMonth(), 1);
  const last = new Date(c.getFullYear(), c.getMonth() + 1, 0);
  $("#cal-label").textContent = c.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  // fetch range +/- pad
  const start = new Date(first); start.setDate(first.getDate() - first.getDay());
  const end = new Date(last); end.setDate(last.getDate() + (6 - last.getDay()));
  const rows = await api(`/api/calendar?start=${start.toISOString()}&end=${end.toISOString()}`);
  const grid = $("#calendar-grid");
  const headers = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
    .map(h => `<div class="cal-head">${h}</div>`).join("");
  const today = new Date();
  const cells = [];
  const cur = new Date(start);
  while (cur <= end) {
    const inMonth = cur.getMonth() === c.getMonth();
    const isToday = cur.toDateString() === today.toDateString();
    const day = new Date(cur);
    const events = rows.filter(r => {
      const d = new Date(r.scheduled_for);
      return d.getFullYear() === day.getFullYear()
        && d.getMonth() === day.getMonth() && d.getDate() === day.getDate();
    });
    cells.push(`
      <div class="cal-cell ${inMonth ? "" : "dim"} ${isToday ? "today" : ""}">
        <div class="num">${day.getDate()}</div>
        ${events.map(ev => `
          <div class="cal-event" data-id="${ev.id}" style="border-left-color:${ev.pillar_color || 'var(--accent)'}">
            <span class="when">${new Date(ev.scheduled_for).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}</span>
            <span>${escape(truncate(ev.title || ev.body || 'Untitled', 38))}</span>
          </div>`).join("")}
      </div>`);
    cur.setDate(cur.getDate() + 1);
  }
  grid.innerHTML = headers + cells.join("");
  grid.querySelectorAll(".cal-event").forEach(e => {
    e.addEventListener("click", () => {
      switchTab("drafts");
      state.selectedDraftId = +e.dataset.id;
      loadDrafts();
    });
  });
}

// =====================================================================
// ANALYTICS
// =====================================================================
async function loadAnalytics() {
  state.analytics = await api("/api/analytics");
  state.drafts = state.drafts.length ? state.drafts : await api("/api/drafts");
  const list = $("#analytics-list");
  if (!state.analytics.length) {
    list.innerHTML = `<div class="muted" style="grid-column:1/-1;padding:30px;text-align:center">
      No analytics yet. Click <b>+ Log a post</b> after you publish.</div>`;
    return;
  }
  list.innerHTML = state.analytics.map(a => `
    <div class="an-card">
      <div class="muted tiny">${fmtDateTime(a.recorded_at)} · ${escape(a.pillar_name || "—")}</div>
      <div style="font-weight:600;margin:4px 0">${escape(a.draft_title || "Untitled")}</div>
      <div class="body-preview">${escape(a.draft_body || "")}</div>
      <div class="nums">
        <div class="num-cell"><div class="v">${(a.impressions||0).toLocaleString()}</div><div class="l">Impr</div></div>
        <div class="num-cell"><div class="v">${a.likes||0}</div><div class="l">Likes</div></div>
        <div class="num-cell"><div class="v">${a.comments||0}</div><div class="l">Comments</div></div>
        <div class="num-cell"><div class="v">${a.follows||0}</div><div class="l">Follows</div></div>
      </div>
      <div class="ed-row" style="margin-top:10px;gap:6px">
        <button class="btn sm" data-repurpose-an="${a.draft_id}">Repurpose this</button>
      </div>
    </div>`).join("");
  list.querySelectorAll("[data-repurpose-an]").forEach(b => {
    b.addEventListener("click", () => repurposeDraft(+b.dataset.repurposeAn));
  });
}

$("#analytics-add").addEventListener("click", () => {
  // need to pick a published draft
  api("/api/drafts").then(drafts => {
    const html = `
      <label>Which post?
        <select id="a-draft">
          ${drafts.map(d => `<option value="${d.id}">${escape(truncate(d.title || d.body, 60))}</option>`).join("")}
        </select>
      </label>
      <div class="form-row">
        <label>Impressions<input id="a-i" type="number" /></label>
        <label>Likes<input id="a-l" type="number" /></label>
      </div>
      <div class="form-row">
        <label>Comments<input id="a-c" type="number" /></label>
        <label>Reposts<input id="a-r" type="number" /></label>
      </div>
      <div class="form-row">
        <label>Followers gained<input id="a-f" type="number" /></label>
        <label>Profile visits<input id="a-pv" type="number" /></label>
      </div>
      <div class="form-row" style="margin-top:14px">
        <button class="btn primary" id="a-save">Log it</button>
        <button class="btn" id="a-cancel">Cancel</button>
      </div>`;
    openModal("Log post performance", html);
    $("#a-cancel").onclick = closeModal;
    $("#a-save").onclick = async () => {
      await api("/api/analytics", {
        method: "POST",
        body: {
          draft_id: +$("#a-draft").value,
          impressions: +$("#a-i").value,
          likes: +$("#a-l").value,
          comments: +$("#a-c").value,
          reposts: +$("#a-r").value,
          follows: +$("#a-f").value,
          profile_visits: +$("#a-pv").value,
        },
      });
      closeModal();
      toast("Logged", "ok");
      loadAnalytics();
    };
  });
});

async function runInsights() {
  const btn = $("#analytics-insights");
  await withSpinner(btn, async () => {
    const r = await api("/api/analytics/insights");
    $("#insights-card").style.display = "";
    $("#insights-text").textContent = r.insight || "(no insight)";
  })();
}
$("#analytics-insights").addEventListener("click", runInsights);

// ---------- LinkedIn CSV import ----------
$("#analytics-import").addEventListener("click", openCsvImporter);

function openCsvImporter() {
  const html = `
    <div class="dropzone" id="dz">
      <div class="big">Drop your LinkedIn analytics file here</div>
      <div>.xlsx or .csv — or click to choose</div>
      <input type="file" id="dz-input" accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
    </div>
    <p class="muted tiny" style="margin-top:10px">
      Get the file from LinkedIn → <b>Creator analytics</b> → <b>Export</b>.
      Personal Creator Analytics ships an .xlsx workbook (Top posts, Discovery,
      Engagement, Followers). The importer auto-picks the sheet with post-level
      analytics, detects columns, and matches each row to a draft by post text
      or date.
    </p>
    <div id="dz-preview"></div>`;
  openModal("Import LinkedIn analytics", html, { wide: true });

  const dz = $("#dz");
  const input = $("#dz-input");
  dz.addEventListener("click", () => input.click());
  ["dragenter", "dragover"].forEach(ev =>
    dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach(ev =>
    dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("dragover"); }));
  dz.addEventListener("drop", e => {
    const f = e.dataTransfer.files[0];
    if (f) handleAnalyticsFile(f);
  });
  input.addEventListener("change", e => {
    const f = e.target.files[0];
    if (f) handleAnalyticsFile(f);
  });
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is "data:...;base64,XXXX" — strip the prefix
      const s = reader.result;
      const i = s.indexOf(",");
      resolve(i >= 0 ? s.slice(i + 1) : s);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// Holds the last-uploaded file context so a sheet pick can re-submit without re-dropping
const importCtx = { xlsx: null, csv: null, fileName: "" };

async function handleAnalyticsFile(file) {
  const preview = $("#dz-preview");
  preview.innerHTML = `<div class="muted" style="padding:14px">
    <span class="spinner"></span> Parsing ${escape(file.name)}…</div>`;
  try {
    const isXlsx = /\.xlsx$/i.test(file.name)
      || file.type.includes("spreadsheetml")
      || file.type.includes("officedocument");
    importCtx.fileName = file.name;
    importCtx.csv = null;
    importCtx.xlsx = null;
    if (isXlsx) {
      importCtx.xlsx = await fileToBase64(file);
    } else {
      importCtx.csv = await file.text();
    }
    await runImportPreview();
  } catch (e) {
    preview.innerHTML = `<div class="muted" style="padding:14px;color:var(--bad)">
      ✗ ${escape(e.message)}</div>`;
  }
}

async function runImportPreview(sheetOverride) {
  const preview = $("#dz-preview");
  const body = {};
  if (importCtx.xlsx) body.xlsx = importCtx.xlsx;
  if (importCtx.csv) body.csv = importCtx.csv;
  if (sheetOverride) body.sheet_override = sheetOverride;

  let r;
  try {
    const res = await fetch("/api/analytics/import-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    r = await res.json();
  } catch (e) {
    preview.innerHTML = `<div class="muted" style="padding:14px;color:var(--bad)">
      ✗ ${escape(e.message)}</div>`;
    return;
  }

  if (r.ok) {
    renderImportPreview(r, { fileName: importCtx.fileName });
  } else if (r.sheets_preview && r.sheets_preview.length) {
    renderSheetPicker(r);
  } else {
    preview.innerHTML = `<div class="muted" style="padding:14px;color:var(--bad)">
      ✗ ${escape(r.error || "Parse failed")}</div>`;
  }
}

function renderSheetPicker(r) {
  const preview = $("#dz-preview");
  const sheetsHtml = r.sheets_preview.map(s => `
    <div class="sheet-card" data-pick="${escape(s.name)}">
      <div class="sheet-head">
        <b>${escape(s.name)}</b>
        <span class="muted tiny">${s.row_count} rows · score ${s.score}</span>
        <button class="btn sm primary" data-pick-btn="${escape(s.name)}">Use this sheet</button>
      </div>
      <div class="sheet-preview">
        ${s.preview.map(row => `
          <div class="sheet-row">${row.map(c =>
            `<span class="sheet-cell">${escape((c || "").toString().slice(0, 60))}</span>`
          ).join("")}</div>`).join("")}
      </div>
    </div>`).join("");
  preview.innerHTML = `
    <div style="padding:10px 0">
      <div style="color:var(--warn);margin-bottom:4px">
        ⚠ ${escape(r.error || "Couldn't auto-detect the right sheet.")}
      </div>
      <div class="muted tiny">
        Pick the sheet that has post-level analytics (date, impressions, likes, comments).
        Workbook: <b>${escape(importCtx.fileName)}</b>
      </div>
    </div>
    <div class="sheet-list">${sheetsHtml}</div>`;
  preview.querySelectorAll("[data-pick-btn]").forEach(b => {
    b.addEventListener("click", e => {
      e.stopPropagation();
      runImportPreview(b.dataset.pickBtn);
    });
  });
}

function renderImportPreview(r, meta = {}) {
  const preview = $("#dz-preview");
  const draftOpts = (selectedId) => `
    <option value="">— skip —</option>
    ${r.drafts.map(d =>
      `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>
        #${d.id} · ${escape(d.title || d.preview || "Untitled").slice(0, 50)}
      </option>`).join("")}`;

  const matched = r.parsed.filter(p => p.matched_draft_id).length;
  const total = r.parsed.length;

  let sheetInfo = "";
  if (r.sheet_used) {
    const allSheets = r.sheets_available || [];
    sheetInfo = `<div style="margin-bottom:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <span class="muted tiny">Workbook <b>${escape(meta.fileName || importCtx.fileName || "")}</b> · sheet</span>
      <select id="switch-sheet" style="width:auto;padding:4px 8px;font-size:12px">
        ${allSheets.map(s =>
          `<option value="${escape(s)}" ${s === r.sheet_used ? "selected" : ""}>${escape(s)}</option>`
        ).join("")}
      </select>
      <span class="muted tiny">${r.parsed.length} rows parsed</span>
    </div>`;
  }

  preview.innerHTML = `
    ${sheetInfo}
    <div class="import-summary">
      <div><b>${total}</b> rows · <b>${matched}</b> auto-matched · ${total - matched} need review</div>
      <button class="btn primary" id="import-confirm">Import ${total} rows</button>
    </div>
    <div style="max-height:50vh;overflow:auto;border:1px solid var(--line);border-radius:8px">
      <table class="import-table">
        <thead><tr>
          <th>Date</th><th>Post snippet</th>
          <th class="num">Impr</th><th class="num">Likes</th>
          <th class="num">Comm</th><th class="num">Reposts</th>
          <th>Match</th>
        </tr></thead>
        <tbody>
          ${r.parsed.map(p => `
            <tr class="${p.matched_draft_id ? '' : 'no-match'}" data-row="${p.row_idx}">
              <td>${escape(p.date || "—")}</td>
              <td class="snippet">${escape((p.snippet || p.url || "(no text)").slice(0, 60))}</td>
              <td class="num">${(p.impressions||0).toLocaleString()}</td>
              <td class="num">${p.likes||0}</td>
              <td class="num">${p.comments||0}</td>
              <td class="num">${p.reposts||0}</td>
              <td>
                <select data-match="${p.row_idx}">
                  ${draftOpts(p.matched_draft_id)}
                </select>
                ${p.match_reason ? `<div class="muted tiny">via ${escape(p.match_reason)}</div>` : ""}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  // Sheet-switch dropdown re-triggers preview with override
  const switchSel = $("#switch-sheet");
  if (switchSel) {
    switchSel.addEventListener("change", e => runImportPreview(e.target.value));
  }

  // Confirm handler
  $("#import-confirm").addEventListener("click", async () => {
    const rows = r.parsed.map(p => {
      const sel = preview.querySelector(`select[data-match="${p.row_idx}"]`);
      const did = sel && sel.value ? +sel.value : null;
      return {
        draft_id: did,
        impressions: p.impressions, likes: p.likes,
        comments: p.comments, reposts: p.reposts, follows: p.follows || 0,
      };
    }).filter(x => x.draft_id);

    if (!rows.length) return toast("Match at least one row first", "error");

    const btn = $("#import-confirm");
    await withSpinner(btn, async () => {
      const res = await api("/api/analytics/import-commit", {
        method: "POST", body: { rows },
      });
      if (!res.ok) return toast(res.error || "Import failed", "error");
      toast(`Imported ${res.created} posts. Skipped ${res.skipped}.`, "ok");
      closeModal();
      loadAnalytics();
      loadDashboard();
    })();
  });
}

// =====================================================================
// ENGAGEMENT
// =====================================================================
async function loadEngagement() {
  state.engagement = await api("/api/engagement");
  const list = $("#engagement-list");
  if (!state.engagement.length) {
    list.innerHTML = `<div class="muted" style="padding:30px;text-align:center">
      No engagement tasks. Add a follow-up reminder or generate comment templates.</div>`;
    return;
  }
  list.innerHTML = state.engagement.map(e => `
    <div class="card" style="display:flex;align-items:center;gap:12px;padding:12px">
      <input type="checkbox" data-id="${e.id}" ${e.completed ? "checked" : ""}
        style="width:auto;flex:0 0 auto"/>
      <div style="flex:1">
        <div style="font-weight:550;${e.completed ? "text-decoration:line-through;opacity:.6" : ""}">
          ${escape(e.details)}
        </div>
        <div class="muted tiny">${e.type} ${e.due_date ? "· due " + fmtDate(new Date(e.due_date)) : ""}</div>
      </div>
      <button class="btn sm danger" data-del="${e.id}">×</button>
    </div>`).join("");
  list.querySelectorAll("input[type=checkbox]").forEach(cb => {
    cb.addEventListener("change", async () => {
      await api(`/api/engagement/${cb.dataset.id}`, {
        method: "PUT", body: { completed: cb.checked ? 1 : 0 },
      });
      loadEngagement();
    });
  });
  list.querySelectorAll("[data-del]").forEach(b => {
    b.addEventListener("click", async () => {
      await api(`/api/engagement/${b.dataset.del}`, { method: "DELETE" });
      loadEngagement();
    });
  });
}

$("#eng-add").addEventListener("click", () => {
  const html = `
    <label>Type
      <select id="e-type">
        <option value="comment">Comment on someone's post</option>
        <option value="follow_up">Reply to my own post comments</option>
        <option value="respond">DM follow-up</option>
      </select>
    </label>
    <label>Details<textarea id="e-details" rows="3" placeholder="Comment on @sarah's K8s post; share the time we hit etcd quorum issues."></textarea></label>
    <label>Due date<input id="e-due" type="date"/></label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="e-save">Add</button>
      <button class="btn" id="e-cancel">Cancel</button>
    </div>`;
  openModal("New engagement task", html);
  $("#e-cancel").onclick = closeModal;
  $("#e-save").onclick = async () => {
    await api("/api/engagement", {
      method: "POST",
      body: {
        type: $("#e-type").value,
        details: $("#e-details").value.trim(),
        due_date: $("#e-due").value || null,
      },
    });
    closeModal();
    loadEngagement();
  };
});

const URL_ONLY_RE = /^https?:\/\/\S+$/;

$("#eng-comments").addEventListener("click", () => {
  const html = `
    <label>Paste the <b>body text</b> of the LinkedIn post (not the URL)
      <textarea id="c-target" rows="8"
        placeholder="On LinkedIn, click ⋯ on the post → Copy text → paste here. URLs alone won't work — we can't fetch them."></textarea>
    </label>
    <p class="muted tiny" style="margin: 4px 0 10px 0">
      Comments are generated in your voice using samples from the Voice tab.
      Add a few past posts there for best results.
    </p>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="c-go">Generate 3 comments ${'✨'}</button>
      <button class="btn" id="c-cancel">Cancel</button>
    </div>
    <div id="c-out" style="margin-top:14px"></div>`;
  openModal("Comment generator", html);
  $("#c-cancel").onclick = closeModal;
  const goBtn = $("#c-go");
  const out = () => $("#c-out");

  function showError(msg) {
    out().innerHTML =
      `<div class="card" style="margin:8px 0;border-color:#b45309">
         <b style="color:#fbbf24">Couldn't generate</b>
         <div style="margin-top:6px;white-space:pre-wrap">${escape(msg)}</div>
       </div>`;
  }

  goBtn.onclick = withSpinner(goBtn, async () => {
    const target = ($("#c-target").value || "").trim();
    if (!target) {
      return showError("Paste the body text of the post first.");
    }
    if (URL_ONLY_RE.test(target)) {
      return showError(
        "That looks like just a URL. Cadence can't fetch LinkedIn URLs " +
        "(LinkedIn's ToS forbids scraping). Open the post on LinkedIn, " +
        "click ⋯ → Copy text, then paste that."
      );
    }
    out().innerHTML = "";

    // 60s timeout via AbortController so the spinner can't hang forever.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60_000);
    let r;
    try {
      const res = await fetch("/api/engagement/comments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_post: target }),
        signal: controller.signal,
      });
      r = await res.json().catch(() => ({ ok: false, error: res.statusText }));
    } catch (e) {
      clearTimeout(timer);
      const isAbort = e.name === "AbortError";
      return showError(isAbort
        ? "Timed out after 60 seconds. Try again, or check your AI backend in Settings."
        : "Network error: " + e.message);
    }
    clearTimeout(timer);

    if (!r.ok) return showError(r.error || "Unknown error.");
    out().innerHTML = r.comments.map(c => `
      <div class="card" style="margin:8px 0">
        <div style="white-space:pre-wrap">${escape(c)}</div>
        <button class="btn sm" style="margin-top:8px"
          onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent);this.textContent='Copied'">
          Copy
        </button>
      </div>`).join("");
  });
});

// =====================================================================
// VOICE
// =====================================================================
async function loadVoice() {
  state.voice = await api("/api/voice");
  $("#voice-list").innerHTML = state.voice.map(v => `
    <div class="voice-card">
      <div class="muted tiny">${escape(v.label || "untitled")} · ${fmtDate(new Date(v.created_at))}</div>
      <div class="content">${escape(v.content)}</div>
      <button class="btn sm danger" data-del="${v.id}" style="align-self:flex-start">Remove</button>
    </div>`).join("") || `<div class="muted" style="grid-column:1/-1;padding:30px;text-align:center">
      No samples yet. Add 5–10 of your strongest past posts.</div>`;
  $$("#voice-list [data-del]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/voice/${b.dataset.del}`, { method: "DELETE" });
    loadVoice();
  }));
}
$("#voice-add").addEventListener("click", () => {
  const html = `
    <label>Label (optional)<input id="v-label" placeholder="e.g. story, contrarian, top-performer"/></label>
    <label>Paste a past post
      <textarea id="v-content" rows="10" placeholder="Paste exactly as you'd post it on LinkedIn."></textarea>
    </label>
    <div class="form-row" style="margin-top:14px">
      <button class="btn primary" id="v-save">Add sample</button>
      <button class="btn" id="v-cancel">Cancel</button>
    </div>`;
  openModal("Add voice sample", html);
  $("#v-cancel").onclick = closeModal;
  $("#v-save").onclick = async () => {
    const c = $("#v-content").value.trim();
    if (!c) return toast("Paste something first", "error");
    await api("/api/voice", {
      method: "POST", body: { content: c, label: $("#v-label").value.trim() },
    });
    closeModal();
    loadVoice();
  };
});

// =====================================================================
// SETTINGS
// =====================================================================
async function loadSettings() {
  await loadPillars();
  const s = await api("/api/settings");
  $("#set-name").value = s.creator_name || "";
  $("#set-handle").value = s.creator_handle || "";
  $("#set-bio").value = s.creator_bio || "";
  $("#set-audience").value = s.target_audience || "";
  $("#set-weekly").value = s.weekly_target || "5";
  $("#set-hours").value = s.preferred_hours || "09:00,17:30";
  $("#set-format").value = s.default_format || "story";
  // pillars
  const pl = $("#pillar-list");
  pl.innerHTML = state.pillars.map(p => `
    <div class="pillar-row" data-id="${p.id}">
      <span class="swatch" style="background:${p.color}"></span>
      <input data-f="name" value="${escape(p.name)}"/>
      <input data-f="description" value="${escape(p.description || "")}"/>
      <input data-f="target_pct" type="number" min="0" max="100" value="${p.target_pct || 0}"/>
      <input data-f="color" type="color" value="${p.color}"/>
      <button class="btn sm danger" data-del="${p.id}">×</button>
    </div>`).join("");
  pl.querySelectorAll(".pillar-row").forEach(row => {
    row.querySelectorAll("input").forEach(input => {
      input.addEventListener("change", async () => {
        const updates = {};
        row.querySelectorAll("input").forEach(i => updates[i.dataset.f] = i.value);
        await api(`/api/pillars/${row.dataset.id}`, { method: "PUT", body: updates });
        toast("Pillar saved", "ok");
        loadPillars();
      });
    });
  });
  pl.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("Delete this pillar?")) return;
    await api(`/api/pillars/${b.dataset.del}`, { method: "DELETE" });
    loadSettings();
  }));
  renderAuthCards(s.auth || {});
  refreshApiStatus(s.auth?.provider && s.auth.provider !== "none");
}

function renderAuthCards(a) {
  // Summary line
  const summary = $("#auth-summary");
  if (a.provider === "api") summary.textContent = "Using API key";
  else if (a.provider === "cli") summary.textContent = "Using Claude Code CLI";
  else summary.textContent = "No backend configured";

  // CLI card
  const cliCard = $("#auth-card-cli");
  const cliDot = $("#auth-cli-dot");
  const cliChip = $("#auth-cli-chip");
  const cliDetail = $("#auth-cli-detail");
  cliCard.classList.toggle("active", a.provider === "cli");
  if (a.cli_installed) {
    cliDot.className = "dot ok";
    cliChip.textContent = a.provider === "cli" ? "active" : "ready";
    cliChip.className = "status-chip ready";
    cliDetail.innerHTML = `Found at <code>${escape(a.cli_path)}</code> · <span class="muted">${escape(a.cli_version)}</span>`;
  } else {
    cliDot.className = "dot bad";
    cliChip.textContent = "not found";
    cliChip.className = "status-chip discarded";
    cliDetail.textContent = "Install the Claude Code CLI to use your existing browser auth.";
  }

  // API card
  const apiCard = $("#auth-card-api");
  const apiDot = $("#auth-api-dot");
  const apiChip = $("#auth-api-chip");
  const clearBtn = $("#clear-api-key");
  apiCard.classList.toggle("active", a.provider === "api");
  if (a.api_key_set) {
    apiDot.className = "dot ok";
    apiChip.textContent = a.provider === "api" ? "active" : "saved";
    apiChip.className = "status-chip ready";
    if (clearBtn) clearBtn.hidden = false;
  } else {
    apiDot.className = "dot";
    apiChip.textContent = "not set";
    apiChip.className = "status-chip";
    if (clearBtn) clearBtn.hidden = true;
  }

  renderModelPicker(a);
}

// Model picker: dropdown of known models, optional Custom text input,
// Save button. We render fresh each time settings load so the source
// indicator and selection stay in sync with what the backend actually
// resolved via get_model().
function renderModelPicker(a) {
  const sel = $("#set-model");
  if (!sel) return;
  const known = a.known_models || [];
  const dbVal = a.model_setting || "";
  const envVal = a.model_env || "";
  const builtin = a.builtin_default_model || "claude-sonnet-4-5";
  const active = a.active_model || (a.provider === "cli" ? "" : builtin);

  // Build options: known models, then "Custom" sentinel.
  const knownIds = new Set(known.map(m => m.id));
  const customOpt = `<option value="__custom__">Custom…</option>`;
  const useDefaultOpt = `<option value="">(Use env var or built-in default)</option>`;
  const knownOpts = known
    .map(m => `<option value="${escape(m.id)}">${escape(m.label)}</option>`)
    .join("");

  sel.innerHTML = useDefaultOpt + knownOpts + customOpt;

  // Decide which option to select:
  // - If DB is empty: show "Use default"
  // - If DB matches a known model: select that
  // - Otherwise: select Custom and fill the text input
  const customInput = $("#set-model-custom");
  if (!dbVal) {
    sel.value = "";
    customInput.hidden = true;
    customInput.value = "";
  } else if (knownIds.has(dbVal)) {
    sel.value = dbVal;
    customInput.hidden = true;
    customInput.value = "";
  } else {
    sel.value = "__custom__";
    customInput.hidden = false;
    customInput.value = dbVal;
  }

  // Source indicator: tells the user where the active model is coming from.
  const src = $("#model-source");
  if (a.provider === "cli") {
    src.textContent = "n/a (CLI backend)";
    src.style.color = "var(--muted)";
  } else if (dbVal) {
    src.textContent = `active: ${active} (from Settings)`;
    src.style.color = "var(--text)";
  } else if (envVal) {
    src.textContent = `active: ${active} (from CLAUDE_MODEL env)`;
    src.style.color = "var(--text)";
  } else {
    src.textContent = `active: ${active} (built-in default)`;
    src.style.color = "var(--muted)";
  }

  // Blurb for the currently-selected known model
  const blurb = $("#model-blurb");
  const selectedKnown = known.find(m => m.id === sel.value);
  blurb.textContent = selectedKnown ? selectedKnown.blurb : "";

  // Disable controls on CLI mode — the setting wouldn't take effect.
  const cliOnly = a.provider === "cli";
  sel.disabled = cliOnly;
  customInput.disabled = cliOnly;
  $("#save-model").disabled = cliOnly;
  $("#model-row").style.opacity = cliOnly ? "0.6" : "1";
}

$("#set-model")?.addEventListener("change", (e) => {
  const isCustom = e.target.value === "__custom__";
  const customInput = $("#set-model-custom");
  customInput.hidden = !isCustom;
  if (isCustom) {
    customInput.focus();
  }
  // Update blurb for known selections
  const blurb = $("#model-blurb");
  const opt = e.target.selectedOptions[0];
  blurb.textContent = (!isCustom && e.target.value)
    ? (opt.textContent + " — saved on click")
    : (isCustom ? "Paste a full model id (e.g. claude-sonnet-4-5-20250929)." : "");
});

$("#save-model")?.addEventListener("click", async () => {
  const sel = $("#set-model");
  let value;
  if (sel.value === "__custom__") {
    value = ($("#set-model-custom").value || "").trim();
    if (!value) return toast("Paste a model id or pick from the list", "error");
  } else {
    value = sel.value;  // "" means "use default"
  }
  try {
    await api("/api/settings", {
      method: "PUT",
      body: { claude_model: value },
    });
  } catch (e) {
    return toast(e.message || "Save failed", "error");
  }
  toast(value ? `Model set to ${value}` : "Model cleared — using default", "ok");
  loadSettings();
  refreshBrand();
});

$("#save-api-key").addEventListener("click", async () => {
  const key = $("#set-api-key").value.trim();
  if (!key) return toast("Paste a key first", "error");
  await api("/api/settings", { method: "PUT", body: { anthropic_api_key: key } });
  $("#set-api-key").value = "";
  toast("API key saved", "ok");
  loadSettings();
  refreshBrand();
});

$("#test-auth").addEventListener("click", withSpinner($("#test-auth"), async () => {
  $("#test-auth-out").textContent = "";
  const r = await api("/api/auth/test", { method: "POST" });
  if (r.ok) {
    const used = r.used === "cli" ? "Claude Code CLI" : "Anthropic API";
    let msg = `✓ Connected via ${used}. Reply: "${(r.reply||"").slice(0,40)}"`;
    if (r.notes && r.notes.length) {
      msg += ` · note: ${r.notes[0]}`;
    }
    $("#test-auth-out").textContent = msg;
    toast(`Connected via ${used}`, "ok");
  } else {
    $("#test-auth-out").textContent = `✗ ${r.error}`;
    toast(r.error || "Connection failed", "error");
  }
}));

$("#clear-api-key").addEventListener("click", async () => {
  if (!confirm("Remove the saved API key? The tool will fall back to Claude Code CLI.")) return;
  await api("/api/settings/clear-api-key", { method: "POST" });
  toast("API key removed", "ok");
  loadSettings();
  refreshBrand();
});

$("#save-profile").addEventListener("click", async () => {
  await api("/api/settings", {
    method: "PUT",
    body: {
      creator_name: $("#set-name").value,
      creator_handle: $("#set-handle").value,
      creator_bio: $("#set-bio").value,
      target_audience: $("#set-audience").value,
      weekly_target: $("#set-weekly").value,
      preferred_hours: $("#set-hours").value,
      default_format: $("#set-format").value,
    },
  });
  toast("Profile saved", "ok");
  refreshBrand();
});

$("#pillar-add").addEventListener("click", async () => {
  await api("/api/pillars", { method: "POST", body: { name: "New pillar", target_pct: 10 } });
  loadSettings();
});

// =====================================================================
// BACKUP / RESTORE
// =====================================================================
$("#backup-export").addEventListener("click", async () => {
  const r = await fetch("/api/backup/export");
  if (!r.ok) return toast("Export failed", "error");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (r.headers.get("content-disposition") || "")
    .match(/filename="([^"]+)"/)?.[1] || "cadence-backup.json";
  a.click();
  URL.revokeObjectURL(url);
  toast("Backup downloaded", "ok");
});

$("#backup-import").addEventListener("click", () => $("#backup-file").click());

$("#backup-file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  e.target.value = "";
  if (!confirm(
    `Restore from "${file.name}"? This REPLACES all current data ` +
    `(ideas, drafts, voice samples, analytics, pillars, settings).`
  )) return;
  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch {
    return toast("That file isn't valid JSON", "error");
  }
  $("#backup-status").textContent = "restoring…";
  try {
    const r = await api("/api/backup/import", {
      method: "POST", body: { payload, mode: "replace" },
    });
    const total = Object.values(r.imported || {}).reduce((a, b) => a + b, 0);
    $("#backup-status").textContent = `restored ${total} rows`;
    toast(`Restored ${total} rows. Reloading…`, "ok");
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    $("#backup-status").textContent = "";
    toast("Import failed: " + err.message, "error");
  }
});

// =====================================================================
// ONBOARDING — first-run modal
// =====================================================================
function openOnboarding() {
  const html = document.createElement("div");
  html.innerHTML = `
    <p class="muted" style="margin-top:0">
      Welcome. Two minutes of setup and Claude can write in your voice.
      You can change all of this later in Settings.
    </p>
    <label>Your name<input id="ob-name" placeholder="Jane Smith" /></label>
    <label>LinkedIn handle (no @)<input id="ob-handle" placeholder="janesmith" /></label>
    <label>Bio — what you do, what you're known for
      <textarea id="ob-bio" rows="3" placeholder="Senior platform engineer. Writing about Kubernetes, observability, and how to lead infra teams without burning out."></textarea>
    </label>
    <label>Target audience — who you're writing for
      <textarea id="ob-audience" rows="2" placeholder="Mid-to-senior infrastructure engineers and engineering managers at growth-stage startups."></textarea>
    </label>
    <p class="muted tiny" style="margin-top:14px">
      <b>Voice samples (optional but recommended).</b>
      Paste 3 of your best past LinkedIn posts. Claude will sample these on
      every generation so the writing sounds like you, not like AI. You can
      add more anytime in the Voice tab.
    </p>
    <label>Past post 1<textarea id="ob-v1" rows="4"></textarea></label>
    <label>Past post 2<textarea id="ob-v2" rows="4"></textarea></label>
    <label>Past post 3<textarea id="ob-v3" rows="4"></textarea></label>
    <div class="ed-row" style="margin-top:14px">
      <button class="btn primary" id="ob-save">Save and start</button>
      <button class="btn ghost" id="ob-skip">Skip for now</button>
    </div>
  `;
  openModal("Welcome — let's set up your voice", html, { wide: true });
  $("#ob-skip").onclick = closeModal;
  $("#ob-save").onclick = async () => {
    const samples = ["#ob-v1", "#ob-v2", "#ob-v3"]
      .map(s => ({ content: $(s).value.trim(), label: "seed" }))
      .filter(s => s.content);
    await api("/api/onboarding/complete", {
      method: "POST",
      body: {
        creator_name: $("#ob-name").value.trim(),
        creator_handle: $("#ob-handle").value.trim(),
        creator_bio: $("#ob-bio").value.trim(),
        target_audience: $("#ob-audience").value.trim(),
        voice_samples: samples,
      },
    });
    closeModal();
    toast(`Welcome${$("#ob-name").value ? ", " + $("#ob-name").value.trim().split(/\s+/)[0] : ""}.`, "ok");
    refreshBrand();
  };
}

function refreshApiStatus(ok, label) {
  $("#api-status").classList.toggle("ok", !!ok);
  $("#api-status-label").textContent = label || (ok ? "Claude ready" : "no auth");
}

// Shorten a model id for the top bar pill: claude-sonnet-4-5 -> sonnet-4-5
function shortModel(m) {
  if (!m) return "";
  return m.replace(/^claude-/, "");
}

async function refreshBrand() {
  const s = await api("/api/settings");
  $("#brand-sub").textContent = s.creator_name
    ? `${s.creator_name} · @${s.creator_handle || ""}`
    : "Set your profile in Settings";
  const a = s.auth || {};
  if (a.provider === "api") {
    const m = shortModel(a.active_model);
    refreshApiStatus(true, m ? `Claude (API · ${m})` : "Claude (API key)");
  } else if (a.provider === "cli") {
    refreshApiStatus(true, "Claude (CLI)");
  } else {
    refreshApiStatus(false, "no auth — Settings");
  }
}

// =====================================================================
// Boot
// =====================================================================
(async function boot() {
  await refreshBrand();
  await loadPillars();
  switchTab("dashboard");
  try {
    const ob = await api("/api/onboarding/status");
    if (ob.first_run) openOnboarding();
  } catch { /* fresh DB hiccup; harmless */ }
})();
