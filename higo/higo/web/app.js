/* HIGO web client — 의존성 없는 바닐라 JS */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const STATE = { schema: null, entities: [], byId: new Map(), relKo: {}, tabLoaded: new Set() };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.body ? "POST" : "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || res.statusText);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3200);
}

const label = (id) => {
  const e = STATE.byId.get(id);
  return e ? e.label_ko || e.label : id;
};
const yearStr = (y) => (y == null ? "?" : y < 0 ? `BC ${-y}` : String(y));
const pill = (s) => `<span class="pill ${esc(s)}">${esc(s)}</span>`;
const conf = (c) => `<span class="conf" title="확신도 ${(+c).toFixed(2)}"><i style="width:${Math.round(c * 100)}%"></i></span> <span class="small muted">${(+c).toFixed(2)}</span>`;
const nodeLink = (id, text) => `<button class="link" data-node="${esc(id)}">${esc(text ?? label(id))}</button>`;
const edgeLink = (id) => `<button class="link small" data-edge="${esc(id)}">${esc(id)}</button>`;
const TYPE_COLOR = { Person: "--c-person", Work: "--c-work", Concept: "--c-concept", Proposition: "--c-prop", School: "--c-school", Movement: "--c-school", Event: "--c-event" };
const CAT_COLOR = { influence: "--e-influence", succession: "--e-succession", critique: "--e-critique", similarity: "--e-similarity", opposition: "--e-opposition" };
const typeColor = (t) => css(TYPE_COLOR[t] || "--c-other");
const catColor = (c) => css(CAT_COLOR[c] || "--e-other");

function resolveInput(v) {
  v = (v || "").trim();
  if (!v) return null;
  if (STATE.byId.has(v)) return v;
  const low = v.toLowerCase();
  const hit = STATE.entities.find((e) => (e.label_ko || "").toLowerCase() === low || e.label.toLowerCase() === low || (e.aliases || []).some((a) => a.toLowerCase() === low));
  return hit ? hit.id : v;
}

/* ---------------------------------------------------------------- markdown */
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", inList = false;
  const inline = (s) =>
    s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>")
      .replace(/\b(EV\d{5})\b/g, '<span class="tag">$1</span>')
      .replace(/\b(E\d{5})\b/g, '<button class="link" data-edge="$1">$1</button>')
      .replace(/\b((?:prop|person|concept|work):[\w\-]+)/g, '<button class="link" data-node="$1">$1</button>');
  for (const raw of lines) {
    const l = raw.trimEnd();
    const m = l.match(/^(#{1,4})\s+(.*)$/);
    if (/^\s*[-*]\s+/.test(l)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(l.replace(/^\s*[-*]\s+/, ""))}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (m) html += `<h${Math.min(4, m[1].length + 1)}>${inline(m[2])}</h${Math.min(4, m[1].length + 1)}>`;
    else if (l.trim()) html += `<p>${inline(l)}</p>`;
  }
  if (inList) html += "</ul>";
  return html;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  initTheme();
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  document.addEventListener("click", onGlobalClick);
  initSearch();
  const [schema, entities, llm] = await Promise.all([api("/api/schema"), api("/api/entities?limit=5000"), api("/api/llm")]);
  STATE.schema = schema;
  schema.relation_types.forEach((r) => (STATE.relKo[r.name] = r.label_ko));
  setEntities(entities);
  $("#llm-badge").textContent = llm.available ? `LLM: ${llm.model}` : "LLM 꺼짐 · 규칙 기반";
  $("#llm-badge").title = llm.reason || "";
  initExplore();
  initAsk();
  initForms();
  refreshQueueCount();
  const hash = location.hash.slice(1);
  if (hash) showTab(hash);
}

function setEntities(entities) {
  STATE.entities = entities;
  STATE.byId = new Map(entities.map((e) => [e.id, e]));
  const opt = (e) => `<option value="${esc(e.id)}">${esc(e.label_ko || e.label)} · ${esc(e.type)}</option>`;
  $("#dl-nodes").innerHTML = entities.filter((e) => !["Era", "Domain", "Source", "Proposition"].includes(e.type)).map(opt).join("");
  $("#dl-persons").innerHTML = entities.filter((e) => e.type === "Person").map(opt).join("");
  $("#dl-concepts").innerHTML = entities.filter((e) => e.type === "Concept").map(opt).join("");
  $("#dl-works").innerHTML = entities.filter((e) => e.type === "Work").map(opt).join("");
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("higo-theme"); } catch (_) {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("higo-theme", next); } catch (_) {}
    GRAPH.draw();
  });
}

function showTab(name) {
  if (!$("#tab-" + name)) return;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  history.replaceState(null, "", "#" + name);
  const loaders = { contradictions: loadContradictions, crossdomain: loadCrossDomain, review: loadReview, ontology: loadOntology, dna: loadLandscape };
  if (loaders[name] && (!STATE.tabLoaded.has(name) || name === "review")) {
    STATE.tabLoaded.add(name);
    loaders[name]();
  }
  if (name === "explore") GRAPH.resize();
}

function onGlobalClick(ev) {
  const n = ev.target.closest("[data-node]");
  const e = ev.target.closest("[data-edge]");
  if (n) { ev.preventDefault(); openNode(n.dataset.node); }
  else if (e) { ev.preventDefault(); openEdge(e.dataset.edge); }
}

function openNode(id) {
  showTab("explore");
  GRAPH.focus(id);
  showNodeDetail(id);
}
function openEdge(id) {
  showTab("explore");
  showEdgeDetail(id);
}

/* ---------------------------------------------------------------- search */
function initSearch() {
  const input = $("#search-input"), box = $("#search-results");
  let t;
  input.addEventListener("input", () => {
    clearTimeout(t);
    const q = input.value.trim();
    if (!q) { box.hidden = true; return; }
    t = setTimeout(async () => {
      const hits = await api("/api/search?q=" + encodeURIComponent(q));
      box.innerHTML = hits.length
        ? hits.map((h) => `<button type="button" data-node="${esc(h.id)}"><span class="dot" style="background:${typeColor(h.type)}"></span>${esc(h.label)} <span class="small muted">${esc(h.type)} · ${yearStr(h.year)}</span></button>`).join("")
        : '<p class="muted small" style="padding:8px">결과 없음</p>';
      box.hidden = false;
    }, 180);
  });
  box.addEventListener("click", () => (box.hidden = true));
  $("#global-search").addEventListener("submit", (e) => e.preventDefault());
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) box.hidden = true; });
}

/* ---------------------------------------------------------- graph canvas */
const GRAPH = {
  nodes: [], edges: [], byId: new Map(), scale: 1, tx: 0, ty: 0, hover: null, selected: null, dragging: null, raf: 0, alpha: 0,
  types: new Set(["Person", "School"]),
  cats: new Set(["influence", "succession", "critique", "similarity", "opposition"]),

  init() {
    this.canvas = $("#graph-canvas");
    this.ctx = this.canvas.getContext("2d");
    new ResizeObserver(() => this.resize()).observe(this.canvas.parentElement);
    const c = this.canvas;
    let panning = null;
    c.addEventListener("pointerdown", (ev) => {
      const p = this.toWorld(ev), n = this.hit(p);
      c.setPointerCapture(ev.pointerId);
      if (n) { this.dragging = n; n.fixed = true; this.selected = n; showNodeDetail(n.id); this.kick(0.3); }
      else panning = { x: ev.clientX, y: ev.clientY, tx: this.tx, ty: this.ty };
    });
    c.addEventListener("pointermove", (ev) => {
      const p = this.toWorld(ev);
      if (this.dragging) { this.dragging.x = p.x; this.dragging.y = p.y; this.kick(0.2); return; }
      if (panning) { this.tx = panning.tx + ev.clientX - panning.x; this.ty = panning.ty + ev.clientY - panning.y; this.draw(); return; }
      const h = this.hit(p);
      if (h !== this.hover) { this.hover = h; c.style.cursor = h ? "pointer" : "grab"; this.draw(); }
    });
    const up = () => { if (this.dragging) this.dragging.fixed = false; this.dragging = null; panning = null; };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const r = c.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
      const k = Math.exp(-ev.deltaY * 0.0015), s = Math.min(4, Math.max(0.15, this.scale * k));
      this.tx = mx - ((mx - this.tx) * s) / this.scale;
      this.ty = my - ((my - this.ty) * s) / this.scale;
      this.scale = s;
      this.draw();
    }, { passive: false });
  },
  resize() {
    const r = this.canvas.getBoundingClientRect(), d = devicePixelRatio || 1;
    if (!r.width) return;
    this.canvas.width = r.width * d; this.canvas.height = r.height * d;
    this.ctx.setTransform(d, 0, 0, d, 0, 0);
    this.w = r.width; this.h = r.height;
    this.draw();
  },
  toWorld(ev) {
    const r = this.canvas.getBoundingClientRect();
    return { x: (ev.clientX - r.left - this.tx) / this.scale, y: (ev.clientY - r.top - this.ty) / this.scale };
  },
  hit(p) {
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i], rr = n.r + 3;
      if ((n.x - p.x) ** 2 + (n.y - p.y) ** 2 < rr * rr) return n;
    }
    return null;
  },
  async load() {
    const types = [...this.types];
    const statuses = $("#show-hyp").checked ? "accepted,revised,proposed,contested,hypothesis" : "";
    const data = await api(`/api/graph?types=${types.join(",")}${statuses ? "&status=" + statuses : ""}`);
    const catSet = this.cats;
    const edges = data.edges.filter((e) => catSet.has(e.category) || (catSet.has("other") && !CAT_COLOR[e.category]));
    const deg = new Map();
    edges.forEach((e) => { deg.set(e.source, (deg.get(e.source) || 0) + 1); deg.set(e.target, (deg.get(e.target) || 0) + 1); });
    const keep = data.nodes.filter((n) => deg.get(n.id) || n.type === "Person");
    const old = this.byId;
    this.nodes = keep.map((n) => {
      const o = old.get(n.id);
      const d = deg.get(n.id) || 0;
      // 초기 x 는 연대 순 — 계보가 왼쪽에서 오른쪽으로 흐르도록
      const x0 = n.year == null ? (Math.random() - 0.5) * 400 : this.timeAxis(n.year);
      return { ...n, deg: d, r: 4 + Math.min(10, Math.sqrt(d) * 2), x: o ? o.x : x0 + (Math.random() - 0.5) * 60, y: o ? o.y : (Math.random() - 0.5) * 600, vx: 0, vy: 0 };
    });
    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    this.edges = edges.filter((e) => this.byId.has(e.source) && this.byId.has(e.target)).map((e) => ({ ...e, s: this.byId.get(e.source), t: this.byId.get(e.target) }));
    this.kick(1);
    if (!old.size) setTimeout(() => this.fit(), 900);
  },
  kick(a) { this.alpha = Math.max(this.alpha, a); if (!this.raf) this.raf = requestAnimationFrame(() => this.tick()); },
  tick() {
    this.raf = 0;
    const N = this.nodes, a = this.alpha;
    // 반발력 (O(n²) — Phase 1 규모에서는 충분)
    for (let i = 0; i < N.length; i++) {
      const p = N[i];
      for (let j = i + 1; j < N.length; j++) {
        const q = N[j];
        let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy + 0.01;
        if (d2 > 250000) continue;
        const f = (900 * a) / d2;
        p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      }
    }
    for (const e of this.edges) {
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = ((d - 70) / d) * 0.04 * a;
      e.s.vx += dx * f; e.s.vy += dy * f; e.t.vx -= dx * f; e.t.vy -= dy * f;
    }
    for (const n of N) {
      // 연대 축 유지 + 중심 인력
      if (n.year != null && this.timeAxis) n.vx += ((this.timeAxis(n.year) - n.x) * 0.01) * a;
      n.vy += -n.y * 0.002 * a;
      if (n.fixed) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.6; n.vy *= 0.6;
      n.x += n.vx; n.y += n.vy;
    }
    this.alpha *= 0.985;
    this.draw();
    if (this.alpha > 0.02) this.raf = requestAnimationFrame(() => this.tick());
  },
  timeAxis(y) {
    // 비선형 연대 축: 고대는 압축, 근대는 확장
    const k = Math.sign(y - 1500) * Math.log1p(Math.abs(y - 1500) / 60);
    return k * 220;
  },
  fit() {
    if (!this.nodes.length || !this.w) return;
    const xs = this.nodes.map((n) => n.x), ys = this.nodes.map((n) => n.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    this.scale = Math.min(2, 0.9 * Math.min(this.w / (x1 - x0 + 60), this.h / (y1 - y0 + 60)));
    this.tx = this.w / 2 - ((x0 + x1) / 2) * this.scale;
    this.ty = this.h / 2 - ((y0 + y1) / 2) * this.scale;
    this.draw();
  },
  focus(id) {
    const n = this.byId.get(id);
    if (!n) { this.selected = null; this.draw(); return; }
    this.selected = n;
    this.tx = this.w / 2 - n.x * this.scale;
    this.ty = this.h / 2 - n.y * this.scale;
    this.draw();
  },
  draw() {
    const ctx = this.ctx;
    if (!ctx || !this.w) return;
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.save();
    ctx.translate(this.tx, this.ty);
    ctx.scale(this.scale, this.scale);
    const focus = this.hover || this.selected;
    const nbr = new Set();
    if (focus) this.edges.forEach((e) => { if (e.s === focus) nbr.add(e.t); if (e.t === focus) nbr.add(e.s); });
    for (const e of this.edges) {
      const on = !focus || e.s === focus || e.t === focus;
      ctx.globalAlpha = on ? Math.max(0.35, e.confidence || 0.5) : 0.06;
      ctx.strokeStyle = catColor(e.category);
      ctx.lineWidth = (on && focus ? 1.8 : 1) / Math.sqrt(this.scale);
      ctx.setLineDash(e.epistemic_status === "hypothesis" || e.epistemic_status === "contested" ? [4, 4] : []);
      ctx.beginPath(); ctx.moveTo(e.s.x, e.s.y); ctx.lineTo(e.t.x, e.t.y); ctx.stroke();
      // 방향 화살표
      if (on && e.category !== "similarity" && e.category !== "opposition") {
        const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 1;
        const ux = dx / d, uy = dy / d, px = e.t.x - ux * (e.t.r + 3), py = e.t.y - uy * (e.t.r + 3);
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px - ux * 7 - uy * 3.5, py - uy * 7 + ux * 3.5); ctx.lineTo(px - ux * 7 + uy * 3.5, py - uy * 7 - ux * 3.5); ctx.fill();
      }
    }
    ctx.setLineDash([]);
    const surf = css("--surface"), text = css("--text");
    for (const n of this.nodes) {
      const on = !focus || n === focus || nbr.has(n);
      ctx.globalAlpha = on ? 1 : 0.18;
      ctx.fillStyle = typeColor(n.type);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
      if (n === this.selected) { ctx.lineWidth = 3 / this.scale; ctx.strokeStyle = text; ctx.stroke(); }
      if (on && (n.type === "Person" || this.scale > 0.8 || n.deg > 6 || n === focus || nbr.has(n))) {
        const fs = 11 / this.scale;
        ctx.font = `${n === focus ? 600 : 400} ${fs}px system-ui, sans-serif`;
        ctx.lineWidth = 3 / this.scale; ctx.strokeStyle = surf; ctx.fillStyle = text;
        const s = (n.label_ko || n.label).slice(0, 22);
        ctx.strokeText(s, n.x + n.r + 3, n.y + 4); ctx.fillText(s, n.x + n.r + 3, n.y + 4);
      }
    }
    ctx.restore();
  },
};

function initExplore() {
  const types = ["Person", "School", "Concept", "Work", "Proposition", "Event"];
  const tnames = { Person: "인물", School: "학파", Concept: "개념", Work: "저작", Proposition: "명제", Event: "사건" };
  $("#type-filter").insertAdjacentHTML("beforeend", types.map((t) => `<button type="button" class="chip" data-type="${t}" aria-pressed="${GRAPH.types.has(t)}"><span class="dot" style="background:${typeColor(t)}"></span>${tnames[t]}</button>`).join(""));
  const cats = [["influence", "영향"], ["succession", "계승·변형"], ["critique", "비판"], ["similarity", "유사"], ["opposition", "대립"], ["other", "기타"]];
  $("#cat-filter").insertAdjacentHTML("beforeend", cats.map(([c, n]) => `<button type="button" class="chip" data-cat="${c}" aria-pressed="${GRAPH.cats.has(c)}"><span class="line" style="border-color:${catColor(c)}"></span>${n}</button>`).join(""));
  $("#type-filter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-type]"); if (!b) return;
    const t = b.dataset.type;
    GRAPH.types.has(t) ? GRAPH.types.delete(t) : GRAPH.types.add(t);
    if (t === "School") GRAPH.types.has(t) ? GRAPH.types.add("Movement") : GRAPH.types.delete("Movement");
    b.setAttribute("aria-pressed", GRAPH.types.has(t));
    GRAPH.load();
  });
  $("#cat-filter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-cat]"); if (!b) return;
    const c = b.dataset.cat;
    GRAPH.cats.has(c) ? GRAPH.cats.delete(c) : GRAPH.cats.add(c);
    b.setAttribute("aria-pressed", GRAPH.cats.has(c));
    GRAPH.load();
  });
  $("#show-hyp").addEventListener("change", () => GRAPH.load());
  $("#graph-reset").addEventListener("click", () => GRAPH.fit());
  $("#legend").innerHTML = `<span><span class="line" style="border-color:${catColor("influence")}"></span>영향</span><span><span class="line" style="border-color:${catColor("succession")}"></span>계승·변형</span><span><span class="line" style="border-color:${catColor("critique")}"></span>비판</span><span><span class="line" style="border-color:${catColor("similarity")}"></span>유사(비인과)</span><span><span class="line dash" style="border-color:${css("--muted")}"></span>가설·이의</span><span class="muted">가로축 ≈ 연대</span>`;
  GRAPH.types.add("Movement");
  GRAPH.init();
  GRAPH.load();
}

async function showNodeDetail(id) {
  const box = $("#detail");
  box.innerHTML = '<p class="loading">불러오는 중…</p>';
  let d;
  try { d = await api("/api/entities/" + encodeURIComponent(id)); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  const n = d.entity, p = n.props || {};
  const groups = Object.entries(d.relations).sort((a, b) => b[1].length - a[1].length);
  const actions = [];
  if (n.type === "Concept") actions.push(`<button class="small" data-act="gen">계보</button>`);
  if (n.type === "Person") actions.push(`<button class="small" data-act="dna">사상 DNA</button>`);
  box.innerHTML = `
    <div class="row"><span class="dot" style="background:${typeColor(n.type)}"></span><span class="small muted">${esc(n.type)} · ${esc(n.id)}</span></div>
    <h2 style="margin-top:6px">${esc(n.label_ko || n.label)}</h2>
    ${n.label_ko && n.label !== n.label_ko ? `<p class="muted small">${esc(n.label)}</p>` : ""}
    ${p.statement ? `<p>${esc(p.statement)}</p>${p.statement_en ? `<p class="small muted">${esc(p.statement_en)}</p>` : ""}` : ""}
    ${n.description ? `<p class="small">${esc(n.description)}</p>` : ""}
    <dl class="kv">
      ${d.year != null ? `<dt>연대</dt><dd>${yearStr(n.start_year)}${n.end_year != null && n.end_year !== n.start_year ? " – " + yearStr(n.end_year) : ""} · ${esc(d.era)}</dd>` : ""}
      ${p.locator ? `<dt>위치</dt><dd>${esc(p.locator)}</dd>` : ""}
      ${d.domains.length ? `<dt>분야</dt><dd>${d.domains.map((x) => esc(x.label)).join(", ")}</dd>` : ""}
      ${(n.aliases || []).length ? `<dt>별칭</dt><dd>${n.aliases.map(esc).join(", ")}</dd>` : ""}
    </dl>
    <div class="row" style="margin-top:8px">${actions.join("")}</div>
    ${groups.map(([k, rels]) => `
      <div class="rel-group"><h3>${esc(rels[0].predicate_ko)} <span class="muted">(${esc(k)})</span> · ${rels.length}</h3>
        ${rels.slice(0, 40).map((r) => `<div class="rel">${r.outgoing ? "→" : "←"} ${nodeLink(r.other, r.other_label)} ${r.evidence_count ? `<span class="small muted" style="white-space:nowrap">증거 ${r.evidence_count}</span>` : ""} ${r.epistemic_status !== "accepted" ? pill(r.epistemic_status) : ""} <span style="margin-left:auto">${edgeLink(r.edge_id)}</span></div>`).join("")}
      </div>`).join("")}`;
  box.querySelector('[data-act="gen"]')?.addEventListener("click", () => { $("#gen-concept").value = id; showTab("genealogy"); runGenealogy(); });
  box.querySelector('[data-act="dna"]')?.addEventListener("click", () => { $("#dna-person").value = id; showTab("dna"); runDNA(); });
}

function evidenceHTML(list) {
  if (!list || !list.length) return '<p class="muted small">증거 없음</p>';
  const tiers = Object.fromEntries((STATE.schema?.evidence_tiers || []).map((t) => [t.tier, t.label_ko]));
  return list.map((e) => `<div class="evidence t${e.tier} ${e.stance}">
    <div><b>Tier ${e.tier}</b> <span class="small muted">${esc(tiers[e.tier] || "")}</span> ${e.stance === "contradicts" ? '<span class="pill rejected" style="text-decoration:none">반대 증거</span>' : ""}</div>
    <div>${e.source_id ? nodeLink(e.source_id, e.source_label || label(e.source_id)) : esc(e.citation)} ${e.locator ? `<span class="muted">· ${esc(e.locator)}</span>` : ""}</div>
    ${e.quotation ? `<div class="small">“${esc(e.quotation)}”</div>` : ""}
    ${e.interpretation ? `<div class="small muted">${esc(e.interpretation)}</div>` : ""}
    <div class="small muted">${esc(e.id)} · ${esc(e.added_by)}</div></div>`).join("");
}

async function showEdgeDetail(id) {
  const box = $("#detail");
  box.innerHTML = '<p class="loading">불러오는 중…</p>';
  const e = await api("/api/edges/" + encodeURIComponent(id));
  const errs = e.validation.issues;
  box.innerHTML = `
    <p class="small muted">관계 ${esc(e.id)} · ${esc(e.category)} · v${e.version}</p>
    <h2>${nodeLink(e.source, e.source_label)} <span class="muted">—${esc(e.predicate_ko)}→</span> ${nodeLink(e.target, e.target_label)}</h2>
    <dl class="kv">
      <dt>인식 상태</dt><dd>${pill(e.epistemic_status)}</dd>
      <dt>증거 성격</dt><dd>${esc(e.evidence_status)}</dd>
      <dt>확신도</dt><dd>${conf(e.confidence)}</dd>
      <dt>기원</dt><dd>${esc(e.origin)}</dd>
      ${e.note ? `<dt>메모</dt><dd>${esc(e.note)}</dd>` : ""}
    </dl>
    ${errs.length ? `<div class="small" style="margin-top:8px">${errs.map((i) => `<div style="color:var(${i.level === "error" ? "--bad" : "--warn"})">${esc(i.code)}: ${esc(i.message)}</div>`).join("")}</div>` : ""}
    <h3 style="margin-top:14px">증거 번들</h3>${evidenceHTML(e.evidence)}
    ${reviewControls(e)}
    <h3 style="margin-top:14px">변경 이력</h3>
    <div class="small">${e.history.map((h) => `<div class="rel"><span class="muted">${new Date(h.ts * 1000).toLocaleString()}</span> <b>${esc(h.action)}</b> ${esc(h.actor)} ${h.after ? `<span class="muted">${esc(JSON.stringify(h.after)).slice(0, 120)}</span>` : ""} ${h.reason ? "— " + esc(h.reason) : ""}</div>`).join("") || '<span class="muted">없음</span>'}</div>`;
  bindReviewControls(box, e.id, () => showEdgeDetail(e.id));
}

function reviewControls(e) {
  const next = (STATE.schema?.status_transitions || {})[e.epistemic_status] || [];
  const acts = [["accepted", "approve", "승인", "ok"], ["rejected", "reject", "기각", "bad"], ["contested", "contest", "이의 제기", ""], ["proposed", "propose", "제안으로", ""]]
    .filter(([s]) => next.includes(s));
  return `<div class="panel" style="margin-top:12px;box-shadow:none">
    <h3>검증</h3>
    <div class="row"><input class="rv-reason grow" placeholder="사유"></div>
    <div class="row" style="margin-top:6px">${acts.map(([, a, t, c]) => `<button class="small ${c}" data-review="${a}">${t}</button>`).join("")}</div>
    <details style="margin-top:8px"><summary class="small">증거 추가</summary>
      <div class="form-grid">
        <select class="ev-tier">${[1, 2, 3, 4, 5, 6].map((t) => `<option value="${t}">Tier ${t}</option>`).join("")}</select>
        <select class="ev-stance"><option value="supports">지지</option><option value="contradicts">반대</option></select>
        <input class="ev-source" list="dl-works" placeholder="원전(work:…) 선택">
        <input class="ev-citation" placeholder="또는 서지 표기">
        <input class="ev-locator" placeholder="쪽·절">
      </div>
      <textarea class="ev-quote" rows="2" placeholder="인용문 (원문 그대로)" style="margin-top:6px"></textarea>
      <button class="small primary ev-add" style="margin-top:6px">증거 추가</button>
    </details></div>`;
}

function reviewer() {
  const v = $("#reviewer").value.trim();
  if (!v) { toast("검증 탭 상단에 검토자 이름을 입력하세요."); showTab("review"); $("#reviewer").focus(); }
  return v;
}

function bindReviewControls(root, edgeId, after) {
  root.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", async () => {
    const actor = reviewer(); if (!actor) return;
    try {
      await api(`/api/edges/${edgeId}/review`, { body: { action: b.dataset.review, actor, reason: root.querySelector(".rv-reason")?.value || "" } });
      toast("상태가 변경되었습니다."); refreshQueueCount(); after && after();
    } catch (e) { toast(e.message); }
  }));
  root.querySelector(".ev-add")?.addEventListener("click", async () => {
    const actor = reviewer(); if (!actor) return;
    const src = resolveInput(root.querySelector(".ev-source").value);
    try {
      await api(`/api/edges/${edgeId}/evidence`, { body: {
        tier: +root.querySelector(".ev-tier").value, stance: root.querySelector(".ev-stance").value,
        source_id: src && STATE.byId.has(src) ? src : null, citation: root.querySelector(".ev-citation").value || (src && !STATE.byId.has(src) ? src : ""),
        locator: root.querySelector(".ev-locator").value, quotation: root.querySelector(".ev-quote").value, actor } });
      toast("증거가 추가되고 확신도가 다시 계산되었습니다."); after && after();
    } catch (e) { toast(e.message); }
  });
}

/* ------------------------------------------------------------------ ask */
const SAMPLE_QS = [
  "자유라는 개념은 고대부터 현대까지 어떻게 변화했는가?",
  "근대적 합리주의는 어디에서 시작되어 어떻게 변형되었는가?",
  "플라톤 → 아리스토텔레스 → 아퀴나스 → 데카르트 → 칸트의 인식론적 연속성과 단절을 찾아라",
  "마르크스와 니체는 근대성에 대해 어떤 공통 문제의식을 가지고 있었으며 어디에서 갈라지는가?",
  "아리스토텔레스는 미국 독립선언에 영향을 주었는가? 제퍼슨과의 연결을 설명하라",
  "애덤 스미스와 마르크스의 노동 개념은 어디에서 갈라지는가?",
  "플라톤과 니체가 진리에 대해 논쟁한다면?",
  "인류 지성사의 핵심 대립 구조는 무엇인가?",
];

function initAsk() {
  $("#ask-samples").innerHTML = SAMPLE_QS.map((q) => `<button type="button" class="ghost">${esc(q)}</button>`).join("");
  $("#ask-samples").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $("#ask-q").value = b.textContent; $("#ask-form").requestSubmit(); });
  $("#ask-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("#ask-q").value.trim(); if (!q) return;
    $("#ask-answer").innerHTML = '<p class="loading">그래프를 따라가는 중…</p>';
    $("#ask-trace").innerHTML = ""; $("#ask-evidence").innerHTML = "";
    try {
      const r = await api("/api/ask", { body: { question: q, use_llm: $("#ask-llm").checked, include_hypotheses: $("#ask-hyp").checked } });
      $("#ask-answer").classList.remove("muted");
      $("#ask-answer").innerHTML = md(r.answer) + `<p class="small muted">합성: ${esc(r.mode)}${r.unsupported_citations.length ? ` · 컨텍스트에 없는 인용 ${r.unsupported_citations.map(esc).join(", ")}` : ""}</p>`;
      $("#ask-trace").innerHTML = r.trace.map((t) => `<li><b>${esc(t.step)}</b> ${esc(Array.isArray(t.detail) ? t.detail.join(" · ") : t.detail)}</li>`).join("");
      $("#ask-evidence").innerHTML = r.evidence.length ? `<div class="table-wrap"><table><thead><tr><th>주장</th><th>Tier</th><th>출처</th><th>확신도</th></tr></thead><tbody>${r.evidence.map((e) => `<tr><td>${esc(e.claim)} ${edgeLink(e.edge_id)}</td><td>${e.tier}</td><td>${esc(e.citation)} <span class="muted">${esc(e.locator)}</span></td><td>${conf(e.confidence)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted small">이 질문에 연결된 증거 관계가 없습니다.</p>';
    } catch (err) { $("#ask-answer").innerHTML = `<p class="muted">${esc(err.message)}</p>`; }
  });
}

/* ------------------------------------------------------------ genealogy */
async function runGenealogy() {
  const id = resolveInput($("#gen-concept").value) || "concept:freedom";
  const out = $("#gen-out");
  out.innerHTML = '<p class="loading">계보를 구성하는 중…</p>';
  try {
    const g = await api("/api/genealogy/" + encodeURIComponent(id));
    out.innerHTML = `<div class="two-col">
      <div class="panel"><h2>${esc(g.label)} — 시대별 타임라인</h2>
        <p class="small muted">개념 계열: ${g.family.map((f) => nodeLink(f.id, f.label) + (f.relation !== "root" ? ` <span class="muted">(${f.relation === "subclass" ? "하위" : "변형"})</span>` : "")).join(", ")}</p>
        <div class="timeline">${g.by_era.map((era) => `<div class="era-h">${esc(era.era)}</div>${era.entries.map((t) => `<div class="tl-item"><span class="tl-year">${yearStr(t.year)}</span> ${t.person ? nodeLink(t.person, t.person_label) : ""} ${t.work ? `『${nodeLink(t.work, t.work_label)}』` : ""} ${t.kind === "proposition" ? `${t.locator ? `<span class="muted small">${esc(t.locator)}</span>` : ""}<div>${nodeLink(t.proposition, t.statement)}</div>` : `<span class="muted">— ${esc(t.concept_label)} ${esc(t.relation_ko)}</span> ${edgeLink(t.edge_id)}`}</div>`).join("")}`).join("")}</div>
      </div>
      <div class="stack">
        <div class="panel"><h2>전승 경로 (인과)</h2>${g.lineage.length ? g.lineage.map((l) => `<div class="path">${nodeLink(l.from, l.from_label)} <span class="arrow">—${esc(l.predicate_ko)}→</span> ${nodeLink(l.to, l.to_label)} ${conf(l.confidence)} ${edgeLink(l.edge_id)}</div>`).join("") : '<p class="muted small">없음</p>'}</div>
        <div class="panel"><h2>개념의 분화·변형</h2>${g.transformations.length ? g.transformations.map((t) => `<div class="path">${nodeLink(t.from, t.from_label)} <span class="arrow">—${esc(t.predicate_ko)}→</span> ${nodeLink(t.to, t.to_label)} ${edgeLink(t.edge_id)}</div>`).join("") : '<p class="muted small">없음</p>'}</div>
      </div></div>`;
  } catch (e) { out.innerHTML = `<p class="panel muted">${esc(e.message)}</p>`; }
}

/* ----------------------------------------------------------- connection */
const KIND_KO = () => STATE.schema?.connection_kinds || {};
function pathHTML(c) {
  if (!c.steps.length) return `<div class="path">${(c.facts || []).map((f) => `<span class="tag">${esc(f.reason)}${f.label ? ": " + esc(f.label) : ""}${f.overlap ? ` (${yearStr(f.overlap[0])}–${yearStr(f.overlap[1])})` : ""}</span>`).join(" ")}</div>`;
  return `<div class="path">${nodeLink(c.steps[0].from, c.steps[0].from_label)}${c.steps.map((s) => ` <span class="arrow">${s.forward ? "" : "←"}${esc(s.predicate_ko)}${s.forward ? "→" : ""}</span> ${edgeLink(s.edge_id)} ${nodeLink(s.to, s.to_label)}`).join("")} <span class="small muted" style="margin-left:auto">강도 ${c.strength.toFixed(2)}</span></div>`;
}
function connectionHTML(r) {
  return `<div class="panel"><h2>${nodeLink(r.from, r.from_label)} → ${nodeLink(r.to, r.to_label)}</h2><p class="verdict">${esc(r.verdict)}</p></div>
    <div class="grid-cards">${Object.entries(r.connections).map(([k, cs]) => `<div class="panel"><h3 class="kind">${esc(k)}</h3><p class="small muted">${esc(KIND_KO()[k] || "역방향 흐름")}</p>${cs.map(pathHTML).join("")}</div>`).join("")}</div>`;
}
async function runConnection() {
  const a = resolveInput($("#conn-a").value), b = resolveInput($("#conn-b").value);
  if (!a || !b) return toast("A 와 B 를 선택하세요.");
  $("#conn-out").innerHTML = '<p class="loading">경로를 찾는 중…</p>';
  try { $("#conn-out").innerHTML = connectionHTML(await api(`/api/connection?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}${$("#conn-hyp").checked ? "&hyp=1" : ""}`)); }
  catch (e) { $("#conn-out").innerHTML = `<p class="panel muted">${esc(e.message)}</p>`; }
}

/* -------------------------------------------------------------- compare */
async function runCompare() {
  const a = resolveInput($("#cmp-a").value), b = resolveInput($("#cmp-b").value);
  if (!a || !b) return toast("두 사상가를 선택하세요.");
  const topic = $("#cmp-topic").value.trim();
  $("#cmp-out").innerHTML = '<p class="loading">명제를 정렬하는 중…</p>';
  try {
    const r = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}${topic ? "&topic=" + encodeURIComponent(topic) : ""}`);
    const pos = (ps) => ps.map((p) => `<div class="quote">“${nodeLink(p.id, p.statement)}” <small>『${esc(p.work || "?")}』 ${esc(p.locator || "")}</small></div>`).join("") || '<p class="muted small">해당 명제 없음</p>';
    $("#cmp-out").innerHTML = `
      <div class="panel"><h2>${nodeLink(r.a, r.a_label)} vs ${nodeLink(r.b, r.b_label)}</h2>
        <p>사상 분포 유사도 <b>${r.similarity.toFixed(2)}</b> · ${esc(r.verdict)}</p>
        ${r.direct_relations.length ? `<p class="small">직접 관계: ${r.direct_relations.map((d) => `${esc(d.source_label)} ${esc(d.predicate_ko)} ${esc(d.target_label)} ${edgeLink(d.edge_id)}`).join(" · ")}</p>` : ""}
        <p class="small muted">두 사람의 말을 섞지 않고, 각자의 명제와 원전 위치를 따라 쟁점별로 나란히 놓습니다.</p></div>
      ${r.issues.map((i, n) => `<div class="panel issue"><div class="row"><h3 style="margin:0">쟁점 ${n + 1}: ${nodeLink(i.concept, i.label)}</h3><span class="stance ${i.stance}">${esc(i.stance_ko)}</span></div>
        <p class="small muted">${esc(i.basis)}</p>
        <div class="cols"><div><b>${esc(r.a_label)}</b>${pos(i.a_positions)}</div><div><b>${esc(r.b_label)}</b>${pos(i.b_positions)}</div></div></div>`).join("") || '<p class="panel muted">공유 개념에 대한 명제가 없습니다.</p>'}
      ${r.cleavages.length ? `<div class="panel"><h3>개념적 분기선</h3>${r.cleavages.map((c) => `<div class="path">${esc(r.a_label)}: ${esc(c.a_concept)} <span class="arrow">↔</span> ${esc(r.b_label)}: ${esc(c.b_concept)} ${edgeLink(c.edge_id)}</div>`).join("")}</div>` : ""}
      <div class="panel two-col"><div><h3>${esc(r.a_label)}에게만</h3><div class="tags">${r.only_a.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div></div><div><h3>${esc(r.b_label)}에게만</h3><div class="tags">${r.only_b.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div></div></div>`;
  } catch (e) { $("#cmp-out").innerHTML = `<p class="panel muted">${esc(e.message)}</p>`; }
}

/* ------------------------------------------------------------------ DNA */
async function runDNA() {
  const id = resolveInput($("#dna-person").value);
  if (!id) return;
  const out = $("#dna-out");
  out.innerHTML = '<p class="loading">계산 중…</p>';
  try {
    const d = await api("/api/dna/" + encodeURIComponent(id));
    const tops = d.domains.filter((x) => !x.top).slice(0, 10);
    const cmax = Math.max(...d.concepts.map((c) => Math.abs(c.score)), 1);
    out.innerHTML = `<h2>${nodeLink(d.id, d.label)} — 사상 DNA</h2>
      <h3>분야 분포</h3>${tops.map((x) => `<div class="bar-row" title="${esc(x.because.join(" / "))}"><span>${esc(x.label)}</span><span class="bar"><i style="width:${x.normalized * 100}%"></i></span><span class="small muted">${x.normalized.toFixed(2)}</span></div>`).join("")}
      <h3 style="margin-top:12px">개념 분포 <span class="small muted">(막대에 마우스를 올리면 근거 명제)</span></h3>
      ${d.concepts.slice(0, 16).map((c) => `<div class="bar-row" title="${esc(c.because.join(" / "))}"><span>${nodeLink(c.id, c.label)}</span><span class="bar ${c.score < 0 ? "neg" : ""}"><i style="width:${(Math.abs(c.score) / cmax) * 100}%"></i></span><span class="small muted">${c.score.toFixed(1)}</span></div>`).join("")}
      <h3 style="margin-top:12px">가까운 사상가 — 왜 비슷한가</h3>
      ${d.similar.map((s) => `<div class="path">${nodeLink(s.id, s.label)} <span class="small muted">${s.similarity.toFixed(2)}</span> <span class="small">공유: ${s.why.map(esc).join(", ") || "—"}</span>${s.disagree_on.length ? ` <span class="small" style="color:var(--bad)">불일치: ${s.disagree_on.map(esc).join(", ")}</span>` : ""}</div>`).join("")}`;
  } catch (e) { out.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function loadLandscape() {
  const box = $("#landscape");
  box.innerHTML = '<p class="loading">투영 중…</p>';
  const l = await api("/api/landscape");
  if (!l.points.length) { box.innerHTML = '<p class="muted">데이터 부족</p>'; return; }
  const W = 560, H = 420, pad = 36;
  const xs = l.points.map((p) => p.x), ys = l.points.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad), sy = (y) => H - pad - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  const groups = [...new Set(l.points.map((p) => p.group))];
  const pal = ["--c-person", "--c-concept", "--c-school", "--c-event", "--c-work", "--hyp", "--warn", "--bad", "--ok"];
  const gc = (g) => (g === "—" ? css("--c-other") : css(pal[groups.indexOf(g) % pal.length]));
  // 겹치는 라벨은 숨긴다 (마우스를 올리면 title 로 이름 표시)
  const placed = [];
  const showLabel = (p) => {
    const x = sx(p.x), y = sy(p.y), w = p.label.length * 10 + 8;
    if (placed.some((q) => x < q.x + q.w && q.x < x + w && Math.abs(q.y - y) < 12)) return false;
    placed.push({ x, y, w });
    return true;
  };
  const ordered = [...l.points].sort((a, b) => Math.hypot(b.x, b.y) - Math.hypot(a.x, a.y));
  const labelled = new Set(ordered.filter(showLabel).map((p) => p.id));
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="사상 지형도">
    <line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="${css("--border")}"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${H - pad}" stroke="${css("--border")}"/>
    ${l.points.map((p) => `<g data-person="${esc(p.id)}"><circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="5" fill="${gc(p.group)}"><title>${esc(p.label)} · ${esc(p.group)}</title></circle>${labelled.has(p.id) ? `<text x="${(sx(p.x) + 7).toFixed(1)}" y="${(sy(p.y) + 3).toFixed(1)}">${esc(p.label)}</text>` : ""}</g>`).join("")}
  </svg>`;
  $("#landscape-axes").innerHTML = l.axes.map((a, i) => `<div>축 ${i + 1}: ${a.loadings.map((x) => `${esc(x.label)}(${x.weight > 0 ? "+" : ""}${x.weight})`).join(", ")}</div>`).join("");
  box.querySelectorAll("[data-person]").forEach((g) => g.addEventListener("click", () => { $("#dna-person").value = g.dataset.person; runDNA(); }));
}

/* ------------------------------------------------------- contradictions */
async function loadContradictions() {
  const out = $("#contra-out");
  out.innerHTML = '<p class="loading">불러오는 중…</p>';
  const r = await api("/api/contradictions");
  const side = (s) => `<div><h3>${nodeLink(s.concept, s.label)}</h3><div class="tags">${s.thinkers.map((t) => nodeLink(t.id, t.label)).join(" · ") || '<span class="muted small">—</span>'}</div></div>`;
  out.innerHTML = `<div class="panel"><h2>인류 지성사의 핵심 논쟁 축</h2><p class="small muted">개념 간 opposed_to / contrasts_with 관계와, 각 편의 명제를 낸 사상가, 그리고 두 편 사이의 실제 비판 관계.</p></div>
    <div class="grid-cards">${r.axes.map((a) => `<div class="panel"><div class="axis">${side(a.sides[0])}<span class="vs">vs</span>${side(a.sides[1])}</div>${a.clashes.length ? `<p class="small" style="margin-top:8px">직접 비판: ${a.clashes.map((c) => `${esc(c.source_label)} → ${esc(c.target_label)} ${edgeLink(c.edge_id)}`).join(" · ")}</p>` : ""}</div>`).join("")}</div>
    <div class="panel"><h2>명제 간 모순</h2><div class="table-wrap"><table><thead><tr><th>명제 A</th><th>명제 B</th><th>상태</th></tr></thead><tbody>
    ${r.proposition_conflicts.map((c) => `<tr><td>${nodeLink(c.a, c.a_statement)} <div class="small muted">${c.a_author.map(esc).join(", ")}</div></td><td>${nodeLink(c.b, c.b_statement)} <div class="small muted">${c.b_author.map(esc).join(", ")}</div></td><td>${pill(c.status)} ${edgeLink(c.edge_id)}</td></tr>`).join("")}</tbody></table></div></div>`;
}

async function loadCrossDomain() {
  const out = $("#cross-out");
  out.innerHTML = '<p class="loading">불러오는 중…</p>';
  const r = await api("/api/cross-domain");
  out.innerHTML = `<div class="two-col"><div class="panel"><h2>분야 사이를 잇는 관계 (Cross-domain Edge)</h2>
    ${r.domain_pairs.map((p) => `<div class="issue"><b>${esc(p.a_label)} ↔ ${esc(p.b_label)}</b> <span class="muted small">${p.count}건</span>${p.examples.map((x) => `<div class="small">${esc(x.source_label)} <span class="muted">—${esc(x.predicate_ko)}→</span> ${esc(x.target_label)} ${edgeLink(x.edge_id)}</div>`).join("")}</div>`).join("")}</div>
    <div class="panel"><h2>경계를 넘나든 사상가</h2><div class="table-wrap"><table><thead><tr><th>인물</th><th>분야</th></tr></thead><tbody>${r.bridge_thinkers.map((b) => `<tr><td>${nodeLink(b.id, b.label)}</td><td>${b.domains.map(esc).join(", ")}</td></tr>`).join("")}</tbody></table></div></div></div>`;
}

/* ------------------------------------------------------------ discovery */
const DISC_KO = { semantic_similarity: "의미적 유사성 (→ similar_to 가설)", transitive_influence: "전이적 영향 사슬 (보고 전용)", concept_cooccurrence: "개념 동시 출현 (→ depends_on 가설)", cross_domain_bridge: "학제 교량 개념", latent_contradiction: "잠재적 모순 (→ contradicted_by 가설)" };
async function runDiscover() {
  const out = $("#disc-out");
  out.innerHTML = '<p class="loading">탐색 중…</p>';
  const r = await api("/api/discover", { body: {} });
  STATE.discovery = r.results;
  out.innerHTML = `<div class="grid-cards">${Object.entries(r.results).map(([k, items]) => `<div class="panel"><h3>${esc(DISC_KO[k] || k)} <span class="muted">${items.length}</span></h3>
    ${items.slice(0, 12).map((it, i) => `<div class="issue small"><div>${nodeLink(it.source, it.source_label)} <span class="muted">—${esc(it.predicate)}→</span> ${nodeLink(it.target, it.target_label)} <span class="muted">(${it.score})</span></div><div class="muted">${esc(it.rationale)}</div>
    ${it.commit_as === "report_only" ? "" : `<button class="small" data-commit="${k}:${i}">가설로 기록</button>`}</div>`).join("") || '<p class="muted small">없음</p>'}</div>`).join("")}</div>`;
  out.querySelectorAll("[data-commit]").forEach((b) => b.addEventListener("click", async () => {
    const [k, i] = b.dataset.commit.split(":");
    try { const e = await api("/api/discover/commit", { body: STATE.discovery[k][+i] }); b.outerHTML = `<span class="small">기록됨 ${edgeLink(e.id)} ${pill(e.epistemic_status)}</span>`; refreshQueueCount(); }
    catch (err) { toast(err.message); }
  }));
}

/* --------------------------------------------------------------- review */
async function refreshQueueCount() {
  try { const q = await api("/api/review/queue"); $("#queue-count").textContent = q.length || ""; } catch (_) {}
}
async function loadReview() {
  const out = $("#review-out");
  out.innerHTML = '<p class="loading">불러오는 중…</p>';
  const [q, cands] = await Promise.all([api("/api/review/queue"), api("/api/candidates")]);
  $("#queue-count").textContent = q.length || "";
  out.innerHTML = `<h2>검토 대기 관계 <span class="muted">${q.length}</span></h2>
    <div class="grid-cards">${q.map((e) => `<div class="panel" data-edge-card="${esc(e.id)}">
      <div class="row">${pill(e.epistemic_status)} <span class="small muted">${esc(e.origin)} · ${esc(e.evidence_status)}</span> <span style="margin-left:auto">${edgeLink(e.id)}</span></div>
      <h3 style="margin:8px 0">${nodeLink(e.source, e.source_label)} <span class="muted">—${esc(STATE.relKo[e.predicate] || e.predicate)}→</span> ${nodeLink(e.target, e.target_label)}</h3>
      <div>${conf(e.confidence)}</div>${e.note ? `<p class="small">${esc(e.note)}</p>` : ""}
      ${evidenceHTML(e.evidence)}
      ${e.validation.issues.filter((i) => i.level === "error").map((i) => `<p class="small" style="color:var(--bad)">승인 불가: ${esc(i.message)}</p>`).join("")}
      ${reviewControls(e)}</div>`).join("") || '<p class="panel muted">대기 중인 관계가 없습니다.</p>'}</div>
    <h2 style="margin-top:16px">추출 후보 <span class="muted">${cands.length}</span></h2>${candidatesHTML(cands)}`;
  out.querySelectorAll("[data-edge-card]").forEach((card) => bindReviewControls(card, card.dataset.edgeCard, loadReview));
  bindCandidates(out, loadReview);
}

function candidatesHTML(cands) {
  if (!cands.length) return '<p class="panel muted small">대기 중인 후보가 없습니다.</p>';
  return `<div class="panel table-wrap"><table><thead><tr><th>종류</th><th>내용</th><th>점수</th><th></th></tr></thead><tbody>${cands.map((c) => {
    const p = c.payload;
    const body = c.kind === "edge" ? `${nodeLink(p.source)} <span class="muted">—${esc(p.predicate)}→</span> ${nodeLink(p.target)}<div class="small muted">“${esc(p.sentence || "")}”</div>`
      : c.kind === "proposition" ? `${esc(p.statement)}<div class="small muted">${esc(label(p.author))} · ${(p.concepts || []).map(label).map(esc).join(", ")}</div>`
      : `${esc(p.type)}: <b>${esc(p.label)}</b><div class="small muted">${esc(p.sentence || p.description || "")}</div>`;
    return `<tr><td>${esc(c.kind)}<div class="small muted">${esc(c.origin)} · ${esc(p.method || "")}</div></td><td>${body}</td><td>${(+c.score).toFixed(2)}</td><td><div class="row"><button class="small ok" data-cand="${c.id}" data-act="approve">채택</button><button class="small bad" data-cand="${c.id}" data-act="reject">버림</button></div></td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function bindCandidates(root, after) {
  root.querySelectorAll("[data-cand]").forEach((b) => b.addEventListener("click", async () => {
    const actor = reviewer(); if (!actor) return;
    try {
      await api(`/api/candidates/${b.dataset.cand}/${b.dataset.act}`, { body: { actor } });
      toast(b.dataset.act === "approve" ? "반영되었습니다 (관계는 가설 상태로 들어갑니다)." : "버렸습니다.");
      setEntities(await api("/api/entities?limit=5000")); refreshQueueCount(); after();
    } catch (e) { toast(e.message); }
  }));
}

/* -------------------------------------------------------------- extract */
const SAMPLE_TEXT = `Spinoza was deeply influenced by Descartes, yet he rejected the mind-body dualism of the Meditations.
헤겔은 스피노자의 영향을 받았지만 실체 일원론을 주체의 변증법으로 재해석했다.
키르케고르는 헤겔을 비판하며 "진리는 주체성이다"라고 주장했다.
Kierkegaard's leap of faith resembles Pascal's wager in its structure.`;

function initForms() {
  $("#gen-go").addEventListener("click", runGenealogy);
  $("#gen-concept").addEventListener("keydown", (e) => e.key === "Enter" && runGenealogy());
  $("#conn-go").addEventListener("click", runConnection);
  $("#cmp-go").addEventListener("click", runCompare);
  $("#dna-go").addEventListener("click", runDNA);
  $("#disc-go").addEventListener("click", runDiscover);
  $("#review-refresh").addEventListener("click", loadReview);
  try { $("#reviewer").value = localStorage.getItem("higo-reviewer") || ""; } catch (_) {}
  $("#reviewer").addEventListener("change", () => { try { localStorage.setItem("higo-reviewer", $("#reviewer").value); } catch (_) {} });
  $("#ex-sample").addEventListener("click", () => { $("#ex-text").value = SAMPLE_TEXT; $("#ex-title").value = "예시: 근대 합리론의 수용과 비판"; });
  $("#ex-go").addEventListener("click", async () => {
    const text = $("#ex-text").value.trim();
    if (!text) return toast("텍스트를 입력하세요.");
    $("#ex-out").innerHTML = '<p class="loading">추출 중…</p>';
    try {
      const r = await api("/api/extract", { body: { title: $("#ex-title").value, text, author_id: resolveInput($("#ex-author").value), work_id: resolveInput($("#ex-work").value), use_llm: $("#ex-llm").checked } });
      $("#ex-out").innerHTML = `<div class="panel small">문서 ${esc(r.document.id)} · 문장 ${r.sentences}개 · 방식 ${esc(r.method)}${r.llm_error ? ` · <span style="color:var(--warn)">LLM: ${esc(r.llm_error)}</span>` : ""} · 후보 ${r.candidates.length}개. 후보는 사람이 채택해야 그래프에 반영됩니다.</div>${candidatesHTML(r.candidates)}`;
      bindCandidates($("#ex-out"), () => {});
      refreshQueueCount();
    } catch (e) { $("#ex-out").innerHTML = `<p class="panel muted">${esc(e.message)}</p>`; }
  });
  $("#gen-concept").value = "concept:freedom";
  $("#conn-a").value = "person:aristotle"; $("#conn-b").value = "person:jefferson";
  $("#cmp-a").value = "person:marx"; $("#cmp-b").value = "person:nietzsche";
  $("#dna-person").value = "person:kant";
}

/* ------------------------------------------------------------- ontology */
async function loadOntology() {
  const out = $("#onto-out");
  out.innerHTML = '<p class="loading">불러오는 중…</p>';
  const [stats, versions, val, hist] = await Promise.all([api("/api/stats"), api("/api/versions"), api("/api/validate"), api("/api/history?limit=40")]);
  const s = STATE.schema;
  out.innerHTML = `
  <div class="grid-cards">
    <div class="panel"><h2>현황</h2><dl class="kv"><dt>스키마</dt><dd>v${esc(stats.schema_version)}</dd><dt>온톨로지</dt><dd>v${esc(stats.ontology_version)}</dd><dt>엔티티</dt><dd>${stats.entities}</dd><dt>관계</dt><dd>${stats.edges}</dd><dt>증거</dt><dd>${stats.evidence}</dd><dt>문서</dt><dd>${stats.documents}</dd></dl>
      <h3 style="margin-top:10px">타입별</h3><div class="tags">${Object.entries(stats.entities_by_type).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join("")}</div>
      <h3 style="margin-top:10px">인식 상태별</h3><div class="tags">${Object.entries(stats.edges_by_status).map(([k, v]) => `${pill(k)} ${v}`).join(" ")}</div></div>
    <div class="panel"><h2>검증 감사</h2><p>${val.ok ? '<span class="pill accepted">스키마 오류 없음</span>' : '<span class="pill rejected" style="text-decoration:none">오류 있음</span>'}</p>
      ${val.issues.slice(0, 30).map((i) => `<div class="small" style="color:var(${i.level === "error" ? "--bad" : "--warn"})">${esc(i.code)} — ${esc(i.message)} ${i.ref ? (i.ref.startsWith("E") ? edgeLink(i.ref) : nodeLink(i.ref)) : ""}</div>`).join("") || '<p class="small muted">경고 없음</p>'}</div>
    <div class="panel"><h2>버전 (Ontology Versioning)</h2>${versions.map((v) => `<div class="rel"><b>v${esc(v.version)}</b> <span class="small muted">${new Date(v.created_at * 1000).toLocaleString()}</span><div class="small">${esc(v.note)}</div></div>`).join("")}
      <div class="row" style="margin-top:8px"><input id="ver-name" placeholder="새 버전 (예: 0.2.0)"><input id="ver-note" placeholder="메모"><button id="ver-go" class="small">스냅샷</button></div>
      <h3 style="margin-top:10px">내보내기</h3><div class="row"><a href="/api/export/json" download="higo.json">JSON</a><a href="/api/export/cypher" download="higo.cypher">Neo4j Cypher</a><a href="/api/export/turtle" download="higo.ttl">RDF/Turtle (OWL)</a></div></div>
  </div>
  <div class="panel"><h2>증거 위계</h2><div class="table-wrap"><table><thead><tr><th>Tier</th><th>종류</th><th>가중치</th></tr></thead><tbody>${s.evidence_tiers.map((t) => `<tr><td>${t.tier}</td><td>${esc(t.label_ko)}</td><td>${t.weight}</td></tr>`).join("")}</tbody></table></div>
    <p class="small muted">확신도 = (지지 증거 noisy-OR) × 증거 성격 계수(${Object.entries(s.evidence_status).map(([k, v]) => `${esc(v.label_ko)} ${v.factor}`).join(", ")}) × (1 − 0.6 × 반대 증거 noisy-OR)</p></div>
  <div class="two-col">
    <div class="panel"><h2>엔티티 타입</h2><div class="table-wrap"><table><thead><tr><th>타입</th><th>설명</th><th>속성</th></tr></thead><tbody>${s.entity_types.map((t) => `<tr><td><b>${esc(t.name)}</b><div class="small muted">${esc(t.label_ko)}</div></td><td>${esc(t.description)}</td><td class="small">${t.properties.map(esc).join(", ")}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="panel"><h2>인식 상태 생애주기</h2>${Object.entries(s.epistemic_status).map(([k, v]) => `<div class="rel">${pill(k)} <span class="small">${esc(v)}</span> <span class="small muted" style="margin-left:auto">→ ${(s.status_transitions[k] || []).join(", ")}</span></div>`).join("")}</div>
  </div>
  <div class="panel"><h2>관계 타입</h2><div class="table-wrap"><table><thead><tr><th>관계</th><th>범주</th><th>설명</th><th>domain → range</th><th>증거 필수</th></tr></thead><tbody>${s.relation_types.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="small muted">${esc(r.label_ko)}</div></td><td><span class="line" style="border-color:${catColor(r.category)}"></span> ${esc(r.category)}</td><td>${esc(r.description)}</td><td class="small">${r.domain.join("|")} → ${r.range.join("|")}${r.symmetric ? " (대칭)" : ""}</td><td>${r.requires_evidence ? "✓" : ""}</td></tr>`).join("")}</tbody></table></div></div>
  <div class="panel"><h2>최근 변경 이력</h2><div class="table-wrap"><table><thead><tr><th>시각</th><th>대상</th><th>행위</th><th>행위자</th><th>사유</th></tr></thead><tbody>${hist.map((h) => `<tr><td class="small">${new Date(h.ts * 1000).toLocaleString()}</td><td>${h.object_kind === "edge" ? edgeLink(h.object_id) : esc(h.object_id)}</td><td>${esc(h.action)}</td><td>${esc(h.actor)}</td><td class="small">${esc(h.reason || "")}</td></tr>`).join("")}</tbody></table></div></div>`;
  $("#ver-go").addEventListener("click", async () => {
    const v = $("#ver-name").value.trim(); if (!v) return;
    await api("/api/versions", { body: { version: v, note: $("#ver-note").value } });
    STATE.tabLoaded.delete("ontology"); loadOntology();
  });
}

boot().catch((e) => { document.body.insertAdjacentHTML("beforeend", `<p class="panel">초기화 실패: ${esc(e.message)}</p>`); });
