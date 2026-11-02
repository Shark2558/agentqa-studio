/* AgentQA Studio Live View: plays the event stream of a run, live or as a replay. */
(() => {
  const L = window.LIVE;
  const AGENTS = [
    { id: "srs", name: "Requirement Analyst", tab: "doc", c: "#4f46e5" },
    { id: "writer", name: "Requirement Writer", tab: "doc", c: "#6d28d9" },
    { id: "explorer", name: "Explorer", tab: "screens", c: "#0369a1" },
    { id: "reconciler", name: "Reconciler", tab: "rules", c: "#b45309" },
    { id: "designer", name: "Planner + Designer", tab: "tests", c: "#0f766e" },
    { id: "importer", name: "Test Importer", tab: "findings", c: "#0891b2" },
    { id: "generator", name: "Script Generator", tab: "code", c: "#334366" },
    { id: "executor", name: "Executor", tab: "screens", c: "#1d4ed8" },
    { id: "exploratory", name: "Exploratory Tester", tab: "screens", c: "#c2410c" },
    { id: "security", name: "Security Scanner", tab: "screens", c: "#7c2d12" },
    { id: "triage", name: "Triage + Bugs", tab: "findings", c: "#c2271d" },
    { id: "healer", name: "Healer", tab: "findings", c: "#be185d" },
    { id: "reporter", name: "Reporter", tab: "findings", c: "#13307a" },
  ];
  const AG = Object.fromEntries(AGENTS.map(a => [a.id, a]));
  AG.pipeline = { id: "pipeline", name: "Pipeline", tab: null, c: "#334155" };
  AG.doctor = { id: "doctor", name: "Readiness check", tab: null, c: "#0f766e" };
  const agent = id => AG[id] || { id, name: id, tab: null, c: "#64748b" };
  const ROLE_COLORS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#9333ea"];
  const roleColor = r => (r === "anonymous" || !r) ? "#64748b" : ROLE_COLORS[Math.max(0, L.roles.indexOf(r)) % ROLE_COLORS.length];
  const TYPE_LABEL = {
    access_denied: "Access control", workflow: "Workflows", page_smoke: "Pages load", form_valid: "Valid submission",
    field_rejects: "Field validation: rejects invalid", field_accepts: "Field validation: accepts valid",
    field_options: "Option lists", field_attribute: "Form attributes", links_ok: "Links", a11y_basic: "Accessibility",
    security_baseline: "Security smoke", security_headers: "Security headers", security_session: "Session ends at logout",
    security_csrf: "Forgery protection (CSRF)", api_smoke: "API health", api_access: "API access control",
    record_isolation: "Record isolation", performance_load: "Load test", visual_snapshot: "Visual snapshots",
    manual_converted: "Imported manual tests", run: "Running",
    "file:test_access": "Access control", "file:test_accessibility": "Accessibility", "file:test_api": "API tests",
    "file:test_forms": "Forms and fields", "file:test_manual": "Imported manual tests", "file:test_pages": "Pages and links",
    "file:test_performance": "Load test", "file:test_security": "Security", "file:test_visual": "Visual snapshots",
    "file:test_workflows": "Workflows",
  };
  const BROWSER_KINDS = new Set(["navigate", "action", "observe", "verdict", "request", "test_start", "test_end", "step", "login", "finding"]);

  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const el = (tag, cls, html) => { const x = document.createElement(tag); if (cls) x.className = cls; if (html != null) x.innerHTML = html; return x; };

  const S = { session: L.session, events: [], cursor: "", running: false, pos: 0, playing: true, follow: true,
              speed: 1, nextAt: 0, tab: null, auto: true, t0: null, quiet: false, loaded: false };
  let M = null;

  const workerName = w => { const m = /^gw(\d+)$/.exec(w || ""); return m ? ` · browser ${Number(m[1]) + 1}` : ""; };
  const shotUrl = name => `/p/${L.slug}/live/${encodeURIComponent(S.session)}/shots/${encodeURIComponent(name)}`;
  const posKey = () => `aq-live-pos:${L.slug}:${S.session}`;
  const savePos = () => { try { sessionStorage.setItem(posKey(), JSON.stringify({ pos: S.pos, follow: S.follow })); } catch (e) {} };
  const loadPos = () => { try { return JSON.parse(sessionStorage.getItem(posKey()) || "null"); } catch (e) { return null; } };
  const fmtT = t => { const s = Math.max(0, Math.round(t - (S.t0 || t))); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

  // ---------------------------------------------------------------- model + reset
  function reset() {
    M = { agents: {}, active: null, activeEvent: null, reqBlocks: {}, curBlock: null, lanes: {}, laneOrder: [],
          nodes: {}, nodeOrder: [], curNode: null, mapDirty: true, ruleCounts: {}, questions: 0, cases: {}, groups: {},
          files: {}, defects: 0, heals: 0, shotsByCase: {}, tests: { total: 0, passed: 0, defect: 0, issue: 0, visual: 0, run: 0 },
          reqs: 0, rules: 0, screens: 0, steps: 0, findings: 0, tabNew: {} };
    for (const id of ["doc", "lanes", "rules", "rulecounts", "wall", "testcounts", "files", "feed"]) $(id).innerHTML = "";
    $("findings").innerHTML = '<div id="f-top"></div><div id="f-list"></div>';
    $("codeprev").textContent = "Generated test code appears here.";
    $("map").innerHTML = "";
    $("now").innerHTML = '<span class="muted">Waiting for the first step...</span>';
    S.pos = 0;
  }

  function buildPipe() {
    const pipe = $("pipe");
    pipe.innerHTML = "";
    for (const a of AGENTS) {
      const n = el("div", "lv-node", `<div class="bar"></div><b>${esc(a.name)}</b><span id="pc-${a.id}">idle</span>`);
      n.id = `pn-${a.id}`;
      n.style.setProperty("--c", a.c);
      n.title = `Show ${a.name}`;
      n.onclick = () => a.tab && showTab(a.tab, true);
      pipe.appendChild(n);
    }
    const f = $("ffilter");
    for (const a of AGENTS) f.appendChild(new Option(a.name, a.id));
    $("legend").innerHTML = L.roles.map(r => `<span><i style="background:${roleColor(r)}"></i>${esc(r)}</span>`).join("") +
      '<span><i style="background:#fca5a5"></i>HTTP error</span><span><i style="background:#ff5a1f"></i>current screen</span>';
  }

  // ---------------------------------------------------------------- apply one event
  function apply(e) {
    if (S.t0 === null) S.t0 = e.t;
    const a = agent(e.agent);
    if (e.agent !== "pipeline") {
      const st = M.agents[e.agent] || (M.agents[e.agent] = { seen: true, done: false });
      if (e.kind === "stage_start") st.done = false;
      if (e.kind === "stage_end" || (e.agent === "importer" && e.kind === "summary")) st.done = true;
      else M.active = e.agent;
    }
    M.activeEvent = e;
    switch (e.agent) {
      case "srs": applyDoc(e); break;
      case "writer":
        if (e.kind === "requirement") {
          const b = M.reqBlocks[e.req];
          const w = el("div", "lv-chip" + (e.flags ? " warn" : ""), esc(`rewritten${e.by && e.by.startsWith("model") ? " by the model" : ""}: ${String(e.title).replace(`${e.req}: `, "")}`) + (e.flags ? " · " + esc(e.flags.join("; ")) : ""));
          if (b) { b.querySelector(".chips").appendChild(w); setCur(b); } else $("doc").appendChild(w);
        } else if (e.kind === "summary" || e.kind === "start") $("doc").appendChild(el("p", "blk", `<b>${esc(e.title)}</b>`));
        break;
      case "reconciler": applyRules(e); break;
      case "designer": applyDesign(e); break;
      case "generator": applyCode(e); break;
      case "triage": case "healer": case "reporter": applyFindings(e); break;
      case "exploratory":
        if (e.kind === "finding") addFinding("bad", SEV[e.severity] || "#ea580c", e.severity, e.title.replace(/^(Critical|High|Medium|Low):\s*/, ""),
          `<div class="muted">Exploratory Tester · ${esc(e.role || "")} · ${esc(e.path || "")}</div><div class="muted">${esc(e.detail || "")}</div>`, false, "xf");
        break;
      case "security":
        if (e.kind === "summary") { M.zap = `${e.alerts} alerts · ${e.findings} for triage`; }
        else if (e.kind === "progress") M.zap = e.title.replace(/^.*?:\s*/, "") ;
        break;
      case "importer":
        if (e.kind === "case" || e.kind === "summary") addFinding(e.level === "warn" ? "warn" : "ok", "#0891b2", "Import", e.title, "", e.kind === "summary");
        break;
      case "pipeline": if (e.kind === "gate") addFinding("warn", "#d97706", "Gate", e.title, "", true); break;
    }
    if ((e.agent === "explorer" || e.agent === "exploratory" || e.agent === "executor" || e.agent === "healer" || e.agent === "security") && BROWSER_KINDS.has(e.kind)) applyBrowser(e);
    if (e.agent === "executor" && (e.kind === "test_start" || e.kind === "test_end")) applyTest(e);
    if (e.agent === "exploratory" && e.kind === "finding") M.findings++;
    addFeed(e, a);
    if (S.auto && a.tab && e.kind !== "stage_end") showTab(a.tab, false);
    else if (a.tab && a.tab !== S.tab) markTab(a.tab);
  }

  // ---- document (Requirement Analyst, then the Requirement Writer's wording)
  function setCur(block) {
    if (M.curBlock) M.curBlock.classList.remove("cur");
    M.curBlock = block;
    block.classList.add("cur");
    if (!S.quiet && S.tab === "doc") keepVisible($("p-doc"), block);
  }
  function keepVisible(panel, item) {
    // scroll only the panel, never the page
    const r = item.getBoundingClientRect(), p = panel.getBoundingClientRect();
    if (r.top < p.top || r.bottom > p.bottom) panel.scrollTop += r.top - p.top - Math.min(140, p.height / 3);
  }
  function highlight(text, terms) {
    let h = esc(text);
    for (const t of terms || []) {
      const re = new RegExp(`(^|[^a-z])(${t.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")})(?![a-z])`, "gi");
      h = h.replace(re, (m, p, w) => `${p}<mark>${w}</mark>`);
    }
    return h;
  }
  function applyDoc(e) {
    const doc = $("doc");
    if (e.kind === "open") doc.appendChild(el("p", "file", `File: <b>${esc(e.file)}</b> · ${e.blocks} block(s)`));
    else if (e.kind === "heading") { const h = el("h4", null, esc(e.title)); doc.appendChild(h); }
    else if (e.kind === "text") { const b = el("div", "blk", esc(e.title)); doc.appendChild(b); setCur(b); }
    else if (e.kind === "table") {
      const rows = e.rows || [];
      const t = el("table");
      t.innerHTML = rows.map((r, i) => `<tr>${r.map(c => i === 0 ? `<th>${esc(c)}</th>` : `<td>${esc(c)}</td>`).join("")}</tr>`).join("");
      const b = el("div", "blk", `<div class="muted small">${esc(e.title)}</div>`); b.appendChild(t); doc.appendChild(b); setCur(b);
    } else if (e.kind === "requirement") {
      M.reqs++;
      const text = String(e.text || e.title).replace(`${e.req}: `, "");
      const b = el("div", "blk req", `<span class="rid">${esc(e.req)}</span>${highlight(text, e.flags)}<div class="chips"></div>`);
      doc.appendChild(b);
      M.reqBlocks[e.req] = b;
      setCur(b);
    } else if (["rule", "ambiguity", "unclear", "model"].includes(e.kind)) {
      let b = M.reqBlocks[e.req];
      if (!b) { b = el("div", "blk req", `<span class="rid">${esc(e.req)}</span><div class="chips"></div>`); doc.appendChild(b); M.reqBlocks[e.req] = b; }
      const chips = b.querySelector(".chips");
      if (e.kind === "rule") {
        M.rules++;
        const v = !e.value ? "" : (typeof e.value === "object" && !Array.isArray(e.value)
          ? " " + Object.entries(e.value).map(([k, x]) => `${k.replace(/_/g, " ")} ${Array.isArray(x) ? x.join("/") : x}`).join(", ")
          : " " + String(e.value));
        const who = e.roles ? ` (${e.roles.join(", ")})` : "";
        chips.appendChild(el("span", "lv-chip" + (e.source === "llm" ? " warn" : ""),
          esc(`${e.rule_kind.replace(/_/g, " ")}${e.field ? " · " + e.field : ""}${v}${who}`) + (e.source === "llm" ? " · model" : "")));
      } else if (e.kind === "ambiguity") chips.appendChild(el("span", "lv-chip warn", esc(`unclear: ${e.term}`)));
      else if (e.kind === "unclear") chips.appendChild(el("span", "lv-chip warn", "no testable rule recognised"));
      else chips.appendChild(el("span", "lv-chip", "asking the local model..."));
      setCur(b);
    } else if (e.kind === "summary") doc.appendChild(el("p", "blk", `<b>${esc(e.title)}</b>`));
  }

  // ---- browser lanes (Explorer, Executor, Exploratory, Healer)
  function lane(e) {
    const key = e.w || "main";
    let ln = M.lanes[key];
    if (ln) return ln;
    const box = el("div", "lv-lane");
    box.innerHTML = `<div class="lv-chrome"><span class="dots"><i></i><i></i><i></i></span><span class="url">about:blank</span>
      <span class="lv-role">-</span><span class="small muted case"></span></div>
      <div class="lv-shotwrap"><div class="empty">No screen yet</div><img alt="Screen the agent is looking at" hidden><div class="lv-box"></div></div>
      <div class="lv-caption"><span class="k"></span><span class="txt"></span></div><div class="lv-verdict" hidden></div><ul class="lv-steps"></ul>`;
    $("lanes").appendChild(box);
    ln = M.lanes[key] = { key, el: box, steps: [], shot: null, shown: null, box: null, vw: 1280, vh: 720, url: "", role: "", case: "",
                          caption: "", agent: e.agent, verdict: null, dirty: true, boxSeq: 0 };
    box.querySelector("img").onerror = function () { this.hidden = true; };
    box.querySelector(".lv-shotwrap").onclick = () => ln.shot && openLightbox(ln.shot, ln.box, ln.vw, ln.vh, ln.caption);
    M.laneOrder.push(key);
    return ln;
  }
  function applyBrowser(e) {
    const ln = lane(e);
    ln.agent = e.agent;
    ln.last = S.pos;
    if (e.url) ln.url = e.url;
    if (e.role) ln.role = e.role;
    if (e.kind === "test_start") { ln.case = e.case || ""; ln.steps = []; ln.verdict = null; }
    if (e.case) ln.case = e.case;
    if (e.shot) { ln.shot = e.shot; ln.vw = e.vw || 1280; ln.vh = e.vh || 720; ln.box = e.box || null; ln.boxSeq++; if (e.case) M.shotsByCase[e.case] = e; }
    else if (e.kind === "action" || e.kind === "navigate") ln.box = null;
    if (e.kind === "verdict") ln.verdict = { level: e.level === "ok" ? "ok" : "bad", text: e.title };
    if (e.kind !== "test_end") { ln.caption = e.title; ln.kind = e.kind; ln.steps.unshift(e.title); ln.steps = ln.steps.slice(0, 6); }
    if (e.kind === "navigate" && e.probe && e.path) { const k = e.path.split("?")[0]; if (M.nodes[k]) { M.curNode = k; M.mapDirty = true; } }
    else if (e.kind === "navigate" && (e.agent === "explorer" || e.agent === "exploratory") && e.path) addNode(e);
    else if (e.kind === "navigate" && e.path && M.nodes[e.path.split("?")[0]]) { M.curNode = e.path.split("?")[0]; M.mapDirty = true; }
    if (e.agent === "explorer" && e.kind === "navigate") M.screens++;
    if (e.agent === "exploratory" && e.kind === "navigate") M.steps++;
    ln.dirty = true;
  }
  function renderLanes() {
    const newest = Math.max(0, ...M.laneOrder.map(k => M.lanes[k].last || 0));
    for (const key of M.laneOrder) {
      const ln = M.lanes[key];
      // a browser that has gone quiet while another works shrinks to its address bar
      ln.el.classList.toggle("idle", newest - (ln.last || 0) > 40);
      if (!ln.dirty) continue;
      ln.dirty = false;
      const b = ln.el, a = agent(ln.agent);
      b.style.setProperty("--c", a.c);
      b.querySelector(".url").textContent = ln.url || "about:blank";
      const role = b.querySelector(".lv-role");
      role.textContent = ln.role || "-";
      role.style.setProperty("--rc", roleColor(ln.role));
      b.querySelector(".case").textContent = `${a.name}${workerName(key)}${ln.case ? " · " + ln.case : ""}`;
      const img = b.querySelector("img");
      if (ln.shot && ln.shown !== ln.shot) {
        img.hidden = false;
        b.querySelector(".empty").hidden = true;
        img.src = shotUrl(ln.shot);
        ln.shown = ln.shot;
      }
      const bx = b.querySelector(".lv-box");
      placeBox(bx, ln.box, ln.vw, ln.vh, ln.boxSeq);
      b.querySelector(".k").textContent = (ln.kind || "").replace("_", " ");
      b.querySelector(".k").style.color = a.c;
      b.querySelector(".txt").textContent = ln.caption;
      const v = b.querySelector(".lv-verdict");
      if (ln.verdict) { v.hidden = false; v.className = `lv-verdict ${ln.verdict.level}`; v.textContent = ln.verdict.text; } else v.hidden = true;
      b.querySelector(".lv-steps").innerHTML = ln.steps.slice(1).map(s => `<li>${esc(s)}</li>`).join("");
    }
  }
  function placeBox(bx, box, vw, vh, seq) {
    if (!box) { bx.classList.remove("on"); return; }
    bx.style.left = `${(box.x / vw) * 100}%`;
    bx.style.top = `${(box.y / vh) * 100}%`;
    bx.style.width = `${(box.width / vw) * 100}%`;
    bx.style.height = `${(box.height / vh) * 100}%`;
    if (bx.dataset.seq !== String(seq)) { bx.classList.remove("on"); void bx.offsetWidth; bx.dataset.seq = String(seq); }
    bx.classList.add("on");
  }

  // ---- site map
  function addNode(e) {
    const path = e.path.split("?")[0] || "/";
    let n = M.nodes[path];
    if (!n) {
      const parent = e.parent ? e.parent.split("?")[0] : null;
      const depth = e.depth != null ? e.depth : (parent && M.nodes[parent] ? M.nodes[parent].depth + 1 : (path === "/" ? 0 : 1));
      n = M.nodes[path] = { path, depth, parent, roles: new Set(), status: e.status, title: e.page_title || "", shot: null };
      M.nodeOrder.push(path);
    }
    n.roles.add(e.role || "anonymous");
    if ((e.status || 0) >= 400) n.status = e.status; else if (!n.status) n.status = e.status;
    if (e.shot) n.shot = e;
    M.curNode = path;
    M.mapDirty = true;
  }
  function renderMap() {
    if (!M.mapDirty) return;
    M.mapDirty = false;
    const svg = $("map");
    const cols = {};
    const pos = {};
    const W = 176, H = 40, GX = 214, GY = 52;
    for (const p of M.nodeOrder) {
      const n = M.nodes[p];
      const d = Math.min(n.depth, 8);
      cols[d] = (cols[d] || 0) + 1;
      pos[p] = { x: 16 + d * GX, y: 16 + (cols[d] - 1) * GY };
    }
    const width = 16 + (Math.max(0, ...Object.keys(cols).map(Number)) + 1) * GX;
    const height = 24 + Math.max(1, ...Object.values(cols)) * GY;
    svg.setAttribute("viewBox", `0 0 ${Math.max(width, 400)} ${height}`);
    svg.setAttribute("width", Math.max(width, 400));
    svg.setAttribute("height", height);
    let html = "";
    for (const p of M.nodeOrder) {
      const n = M.nodes[p], q = n.parent && pos[n.parent];
      if (!q || n.parent === p) continue;
      const a = pos[p];
      const x1 = q.x + W, y1 = q.y + H / 2, x2 = a.x, y2 = a.y + H / 2, mx = (x1 + x2) / 2;
      html += `<path class="edge" d="M${x1} ${y1} C${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}"/>`;
    }
    for (const p of M.nodeOrder) {
      const n = M.nodes[p], a = pos[p];
      const cls = ["node", (n.status || 0) >= 400 ? "bad" : "ok", p === M.curNode ? "cur" : ""].join(" ");
      const label = p.length > 26 ? p.slice(0, 25) + "…" : p;
      const dots = [...n.roles].map((r, i) => `<circle cx="${a.x + W - 10 - i * 11}" cy="${a.y + H - 9}" r="4" fill="${roleColor(r)}"><title>${esc(r)}</title></circle>`).join("");
      html += `<g class="${cls}" data-path="${esc(p)}"><rect x="${a.x}" y="${a.y}" width="${W}" height="${H}" rx="8"/>
        <text x="${a.x + 10}" y="${a.y + 16}" font-size="12" font-weight="600" fill="#18202b">${esc(label)}</text>
        <text x="${a.x + 10}" y="${a.y + 31}" font-size="10.5" fill="#5b6676">${esc(n.status >= 400 ? "HTTP " + n.status : (n.title || "").slice(0, Math.max(6, 24 - n.roles.size * 2.6)))}</text>${dots}</g>`;
    }
    svg.innerHTML = html;
    svg.querySelectorAll(".node").forEach(g => g.onclick = () => {
      const n = M.nodes[g.dataset.path];
      if (n && n.shot) openLightbox(n.shot.shot, null, n.shot.vw, n.shot.vh, `${n.path} - ${n.title}`);
    });
  }

  // ---- rules board (Reconciler)
  const STATUS_CLASS = { Confirmed: "ok", Decided: "ok", Workflow: "ok", Divergent: "bad", "Missing in app": "bad",
                         "SRS-only": "warn", "App-only": "warn", Ambiguous: "warn", Proposed: "warn", Rejected: "", "Not automated": "" };
  function applyRules(e) {
    if (e.kind === "status") {
      M.ruleCounts[e.status] = (M.ruleCounts[e.status] || 0) + 1;
      const r = el("div", "row2", `<span class="rid small">${esc(e.req || "app")}</span>
        <span>${esc((e.rule_kind || "").replace(/_/g, " "))}${e.field ? " · <b>" + esc(e.field) + "</b>" : ""}</span>
        <span><span class="pill ${STATUS_CLASS[e.status] || ""}">${esc(e.status)}</span></span>
        ${e.where || e.note ? `<span class="where">${e.where ? "matched " + esc(e.where) : ""}${e.where && e.note ? " · " : ""}${esc(e.note || "")}</span>` : ""}`);
      $("rules").prepend(r);
    } else if (e.kind === "question") {
      M.questions++;
      $("rules").prepend(el("div", "lv-q", `<b>Question for you:</b> ${esc(e.title)}`));
    } else if (e.kind === "start") {
      $("rules").prepend(el("div", "muted small", esc(e.title)));
    }
    const order = ["Confirmed", "Decided", "Workflow", "Divergent", "SRS-only", "App-only", "Ambiguous", "Proposed", "Missing in app", "Not automated", "Rejected"];
    $("rulecounts").innerHTML = order.filter(k => M.ruleCounts[k]).map(k => `<span class="pill ${STATUS_CLASS[k] || ""}">${M.ruleCounts[k]} ${esc(k)}</span>`).join("") +
      (M.questions ? `<span class="pill warn">${M.questions} question(s)</span>` : "");
  }

  // ---- test wall (Designer + Executor)
  function group(type) {
    if (M.groups[type]) return M.groups[type];
    const g = el("div", "grp", `<h4>${esc(TYPE_LABEL[type] || type)}</h4><div class="lv-tiles"></div>`);
    $("wall").appendChild(g);
    return (M.groups[type] = g.querySelector(".lv-tiles"));
  }
  function tile(id, type, title) {
    let t = M.cases[id];
    if (t) return t;
    t = el("button", "lv-tile", esc(id.replace("TC-", "")));
    t.title = `${id}: ${title || ""}`;
    t.onclick = () => {
      const s = M.shotsByCase[id];
      if (s) openLightbox(s.shot, s.box, s.vw, s.vh, `${id}: ${title || s.title}`);
    };
    group(type).appendChild(t);
    M.cases[id] = t;
    M.tests.total++;
    return t;
  }
  function applyDesign(e) {
    if (e.kind === "case") tile(e.case, e.ctype, e.title.replace(/^TC-\d+\s*/, ""));
    renderTestCounts();
  }
  function applyTest(e) {
    const f = /([\w]+)\.py::/.exec(e.nodeid || "");
    const t = tile(e.case, f ? `file:${f[1]}` : "run", e.title);
    if (e.kind === "test_start") { t.className = "lv-tile run"; M.tests.run++; }
    else {
      M.tests.run = Math.max(0, M.tests.run - 1);
      const cls = e.category === "passed" ? "passed" : (e.category === "defect" ? "defect" : (e.category === "visual" ? "visual" : "issue"));
      t.className = `lv-tile ${cls}`;
      M.tests[cls] = (M.tests[cls] || 0) + 1;
      if (e.message) t.title += `\n${e.message}`;
    }
    renderTestCounts();
  }
  function renderTestCounts() {
    const x = M.tests;
    $("testcounts").innerHTML = `<span class="pill">${x.total} case(s)</span>` +
      (x.run ? `<span class="pill running">${x.run} running</span>` : "") +
      (x.passed ? `<span class="pill ok">${x.passed} passed</span>` : "") +
      (x.defect ? `<span class="pill bad">${x.defect} defect(s)</span>` : "") +
      (x.issue ? `<span class="pill warn">${x.issue} test issue(s)</span>` : "") +
      (x.visual ? `<span class="pill visual-change">${x.visual} visual change(s)</span>` : "");
  }

  // ---- code + findings
  function applyCode(e) {
    if (e.kind !== "write") return;
    M.files[e.file] = e;
    const b = el("button", "ghost", `${esc(e.file)} <span class="muted small">${e.tests}</span>`);
    b.onclick = () => { $("codeprev").textContent = e.preview || ""; };
    $("files").appendChild(b);
    $("codeprev").textContent = e.preview || "";
  }
  const SEV = { Critical: "#a3201b", High: "#c2410c", Medium: "#a16207", Low: "#4b5563" };
  function addFinding(level, color, label, title, extra, top, cls) {
    const d = el("div", "lv-def" + (cls ? " " + cls : ""), `<span class="sev ${esc(label)}">${esc(label)}</span><b>${esc(title)}</b>${extra || ""}`);
    d.style.setProperty("--sc", color);
    if (top) $("f-top").prepend(d); else $("f-list").appendChild(d);
  }
  function applyFindings(e) {
    if (e.agent === "triage" && e.kind === "defect") {
      if (!M.defects) {
        // exploratory findings are now merged into these defects
        const xf = $("f-list").querySelectorAll(".xf");
        if (xf.length) { xf.forEach(x => x.remove()); $("f-top").appendChild(el("div", "muted small", `${xf.length} exploratory finding(s) merged into the defects below`)); }
      }
      M.defects++;
      const title = e.title.replace(/^(Critical|High|Medium|Low):\s*/, "");
      addFinding("bad", SEV[e.severity] || "#64748b", e.severity, title,
        `<div class="muted">${e.roles ? "Roles: " + esc(e.roles.join(", ")) + " · " : ""}${e.reqs ? "Traces to " + esc(e.reqs.join(", ")) + " · " : ""}${e.cases ? esc(e.cases.length + " test(s)") : ""}${e.cases && e.found_by ? " + " : ""}${e.found_by ? "found by the Exploratory Tester" : (e.cases ? "" : "found without a test")}</div>
         <div class="muted">${esc(e.actual || "")}</div>`);
    } else if (e.agent === "healer" && e.kind === "heal") {
      M.heals++;
      addFinding("warn", "#db2777", "Heal", e.title);
    } else if (e.agent === "reporter" && e.kind === "write") {
      addFinding("ok", "#0f766e", "Report", e.title, `<div><a href="/p/${L.slug}/files/reports/report.html" target="_blank">Open the report</a></div>`, true);
    } else if (e.kind === "summary" || e.kind === "start") {
      if (e.agent !== "reporter") $("f-top").appendChild(el("div", "muted small", esc(`${agent(e.agent).name}: ${e.title}`)));
    }
  }

  // ---- feed
  function addFeed(e, a) {
    if (e.kind === "rule" || (e.kind === "case" && S.quiet)) return; // too many to list; shown in their panels
    const lvl = e.level || (e.kind === "issue" || e.kind === "finding" ? "bad" : "");
    const it = el("div", `lv-item ${lvl}${S.quiet ? "" : " new"}`);
    it.dataset.agent = e.agent;
    it.style.setProperty("--c", a.c);
    it.innerHTML = `<span class="tm">${fmtT(e.t)}</span><div><div class="who">${esc(a.name)}${e.role ? " · " + esc(e.role) : ""}${e.case ? " · " + esc(e.case) : ""}</div>
      <div class="txt">${esc(e.title)}</div></div>`;
    if (e.shot) {
      const img = el("img");
      img.loading = "lazy";
      img.alt = e.title;
      img.src = shotUrl(e.shot);
      img.onerror = () => img.remove();
      img.onclick = () => openLightbox(e.shot, e.box, e.vw, e.vh, e.title);
      it.lastElementChild.appendChild(img);
    }
    filterItem(it);
    const feed = $("feed");
    feed.prepend(it);
    while (feed.childElementCount > 400) feed.lastElementChild.remove();
  }
  function filterItem(it) {
    const f = $("ffilter").value, only = $("fissues").checked;
    it.style.display = (f && it.dataset.agent !== f) || (only && !it.classList.contains("bad") && !it.classList.contains("warn")) ? "none" : "";
  }

  // ---------------------------------------------------------------- chrome
  function renderChrome() {
    for (const a of AGENTS) {
      const n = $(`pn-${a.id}`), st = M.agents[a.id];
      n.className = "lv-node" + (st ? " seen" : "") + (st && st.done ? " done" : "") + (M.active === a.id && !(st && st.done && S.pos >= S.events.length && !S.running) ? " active" : "");
      $(`pc-${a.id}`).textContent = counter(a.id, st);
    }
    const e = M.activeEvent;
    if (e) {
      const a = agent(e.agent);
      $("now").style.setProperty("--c", a.c);
      $("now").innerHTML = `<span class="ag" style="background:${a.c}">${esc(a.name)}</span><span>${esc(e.title)}</span>
        <span class="meta">${[e.role, e.case, workerName(e.w).replace(" · ", "")].filter(Boolean).map(esc).join(" · ")}</span>`;
    }
    $("scrub").max = S.events.length;
    $("scrub").value = S.pos;
    $("pos").textContent = `${S.pos} / ${S.events.length}`;
    $("btn-play").innerHTML = S.playing ? "&#10074;&#10074;" : "&#9654;";
    const status = $("status");
    status.textContent = S.running ? "running" : (S.loaded ? (S.pos < S.events.length ? "replaying" : "finished") : "loading");
    status.className = "pill " + (S.running ? "running" : "done");
    for (const t of Object.keys(M.tabNew)) {
      const b = document.querySelector(`#tabs button[data-tab="${t}"]`);
      if (b && !b.querySelector(".dot") && t !== S.tab) b.insertAdjacentHTML("beforeend", '<span class="dot"></span>');
    }
  }
  function counter(id, st) {
    if (!st) return "idle";
    const x = M.tests;
    switch (id) {
      case "srs": return `${M.reqs} requirements · ${M.rules} rules`;
      case "explorer": return `${M.screens} screen visits`;
      case "reconciler": return `${Object.values(M.ruleCounts).reduce((p, c) => p + c, 0)} rules · ${M.questions} questions`;
      case "designer": return `${x.total} cases`;
      case "generator": return `${Object.keys(M.files).length} files`;
      case "executor": return x.passed + x.defect + x.issue ? `${x.passed} passed · ${x.defect} failed` : "starting";
      case "exploratory": return `${M.steps} pages · ${M.findings} findings`;
      case "triage": return `${M.defects} defects`;
      case "healer": return `${M.heals} proposals`;
      case "reporter": return st.done ? "report ready" : "writing";
      case "importer": return st.done ? "imported" : "reading";
      case "security": return M.zap || (st.done ? "done" : "scanning");
    }
    return st.done ? "done" : "working";
  }
  function showTab(tab, pin) {
    if (pin) { S.auto = false; $("auto").checked = false; }
    if (S.tab === tab && !pin) return;
    S.tab = tab;
    document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
    document.querySelectorAll(".lv-panel").forEach(p => p.classList.toggle("on", p.id === `p-${tab}`));
    const b = document.querySelector(`#tabs button[data-tab="${tab}"] .dot`);
    if (b) b.remove();
    delete M.tabNew[tab];
    if (tab === "screens") M.mapDirty = true;
  }
  function markTab(tab) { if (!S.quiet) M.tabNew[tab] = true; }

  // ---------------------------------------------------------------- lightbox
  function openLightbox(shot, box, vw, vh, title) {
    if (!shot) return;
    $("lbtitle").textContent = title || "";
    $("lbimg").src = shotUrl(shot);
    placeBox($("lbbox"), box, vw || 1280, vh || 720, Math.random());
    $("lightbox").hidden = false;
  }
  $("lbclose").onclick = () => { $("lightbox").hidden = true; };
  $("lightbox").onclick = ev => { if (ev.target.id === "lightbox") $("lightbox").hidden = true; };
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape") $("lightbox").hidden = true;
    if (ev.key === " " && ev.target.tagName !== "INPUT" && ev.target.tagName !== "SELECT") { ev.preventDefault(); togglePlay(); }
  });

  // ---------------------------------------------------------------- player
  function dwell(e) {
    let d = 120;
    if (e.shot) d = 650;
    else if (["requirement", "text", "heading", "table"].includes(e.kind)) d = 300;
    else if (["rule", "status", "case", "request"].includes(e.kind)) d = 55;
    else if (["test_start", "test_end", "verdict"].includes(e.kind)) d = 160;
    else if (["stage_start", "stage_end", "gate", "summary", "defect", "question"].includes(e.kind)) d = 450;
    const backlog = S.events.length - S.pos;
    if (S.follow && backlog > 40) d /= Math.min(25, backlog / 12);
    return d / S.speed;
  }
  function render() { renderLanes(); if (S.tab === "screens") renderMap(); renderChrome(); }
  function tick() {
    if (!S.playing || S.pos >= S.events.length) { renderChrome(); return; }
    const now = performance.now();
    if (now < S.nextAt) return;
    if (S.speed === 0) {
      const until = Math.min(S.events.length, S.pos + 600);
      S.quiet = true;
      while (S.pos < until) apply(S.events[S.pos++]);
      S.quiet = false;
    } else {
      const e = S.events[S.pos++];
      apply(e);
      S.nextAt = now + dwell(e);
    }
    if (S.pos % 10 === 0 || S.pos >= S.events.length) savePos();
    render();
  }
  function rebuild(n) {
    reset();
    S.quiet = true;
    while (S.pos < n && S.pos < S.events.length) apply(S.events[S.pos++]);
    S.quiet = false;
    for (const k of M.laneOrder) M.lanes[k].dirty = true;
    M.mapDirty = true;
    render();
  }
  function togglePlay() { S.playing = !S.playing; S.nextAt = 0; renderChrome(); }
  $("btn-play").onclick = togglePlay;
  $("btn-step").onclick = () => { S.playing = false; if (S.pos < S.events.length) { apply(S.events[S.pos++]); render(); savePos(); } };
  $("btn-restart").onclick = () => { S.follow = false; rebuild(0); S.playing = true; savePos(); };
  $("btn-live").onclick = () => { S.follow = true; rebuild(S.events.length); S.playing = true; savePos(); };
  $("speed").onchange = ev => { S.speed = Number(ev.target.value); S.nextAt = 0; };
  $("scrub").oninput = ev => { S.playing = false; S.follow = false; rebuild(Number(ev.target.value)); savePos(); };
  $("auto").onchange = ev => { S.auto = ev.target.checked; };
  $("session").onchange = ev => { location.href = `/p/${L.slug}/live?s=${encodeURIComponent(ev.target.value)}`; };
  $("ffilter").onchange = $("fissues").onchange = () => document.querySelectorAll("#feed .lv-item").forEach(filterItem);
  document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab, true));

  async function poll() {
    if (!S.session) { S.loaded = true; renderChrome(); return; }
    try {
      const r = await fetch(`/p/${L.slug}/live/${encodeURIComponent(S.session)}/events?cursor=${encodeURIComponent(S.cursor)}`);
      if (r.ok) {
        const data = await r.json();
        S.cursor = data.cursor;
        if (data.events.length) S.events.push(...data.events);
        S.running = data.running;
        if (!S.loaded) {
          S.loaded = true;
          // Resume where the viewer last was in this session, instead of replaying from the start every visit.
          const saved = loadPos();
          if (S.running) {
            S.follow = true; rebuild(S.events.length); S.playing = true;          // a live run: jump to the latest step
          } else if (saved && saved.pos > 0 && saved.pos <= S.events.length) {
            S.follow = !!saved.follow; S.speed = 2; $("speed").value = "2";
            rebuild(saved.pos); S.playing = false;                                 // a finished run: back where they left off
          } else {
            S.follow = false; S.speed = 2; $("speed").value = "2";
          }
        }
      }
    } catch (err) { /* server restarting; try again */ }
    renderChrome();
    setTimeout(poll, S.running || !S.loaded ? 800 : 5000);
  }

  // notice runs started elsewhere (another tab, the command line, demo.bat)
  async function watchSessions() {
    try {
      const r = await fetch(`/p/${L.slug}/live-sessions`);
      if (r.ok) {
        const list = (await r.json()).sessions;
        const fresh = list.find(x => x.running && x.id !== S.session);
        if (fresh && (!S.session || !S.running)) {
          if (!S.session || !S.events.length || !L.explicit) { location.href = `/p/${L.slug}/live?s=${encodeURIComponent(fresh.id)}`; return; }
          const b = $("newrun");
          b.hidden = false;
          b.innerHTML = `<b>A new run is in progress:</b> ${esc(fresh.label)} <a class="btn" href="/p/${L.slug}/live?s=${encodeURIComponent(fresh.id)}">Watch it</a>`;
        } else if (!fresh) $("newrun").hidden = true;
      }
    } catch (err) { /* ignore */ }
    setTimeout(watchSessions, 4000);
  }

  window.addEventListener("pagehide", savePos);
  document.addEventListener("visibilitychange", () => { if (document.hidden) savePos(); });
  buildPipe();
  reset();
  watchSessions();
  showTab("doc", false);
  setInterval(tick, 40);
  poll();
})();
