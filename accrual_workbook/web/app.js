/* OpEx Accrual Workbook front end.
   Displays what the API returns and posts edits back. It does no accrual math: every accrual,
   budget, spend and JE amount comes from the engine via /api. Footer rows only add up the rows shown. */
"use strict";

const TABS = [
  ["summary", "Summary"], ["opex", "Vendor OpEx"], ["legal", "Legal"], ["capex", "Capex Projects"],
  ["attention", "Needs Attention"], ["mom", "MoM Review"], ["je", "Journal Entry"], ["history", "History"],
  ["budget", "Budget"], ["ytd", "YTD Transactions"], ["settings", "Settings"],
];

const S = {
  meta: null, period: null, data: null, tab: "summary", history: null, historyPeriod: null, settings: null, uploadMsg: {},
  f: {
    opex: { q: "", vendor: "", acct: "", type: "" },
    capex: { q: "", deal: "", vendor: "" },
    att: { status: "active", category: "", period: "", q: "" },
    mom: { acct: "", q: "", driver: "", att: "", rev: "", size: "", dir: "" },
    je: { section: "" },
    budv: { q: "" }, budva: { q: "" },
    gl: { svc: "", post: "", acct: "", q: "", basis: "", dept: "" },
  },
  sort: { key: "", dir: 1 },
  collapsed: new Set(["scope", "overview", "excluded"]),
  legalDirty: {}, signConfirm: false, ui: { legalAdd: false, attAdd: false },
};
let EXP = {};

// ---------- formatting ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nfmt = (v) => Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (v) => (v === null || v === undefined || v === "" ? "" : Number(v) < 0 ? `($${nfmt(-v)})` : `$${nfmt(v)}`);
const pct = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const amt = (v, cls = "") => `<td class="num amt ${Number(v) < 0 ? "neg" : ""} ${cls}">${money(v)}</td>`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monLabel = (k) => { const [y, m] = k.split("-"); return `${MON[+m - 1]} ${y.slice(2)}`; };
const monthAfter = (k) => { const [y, m] = k.split("-").map(Number); return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`; };
const when = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "");
const sum = (rows, f) => rows.reduce((a, r) => a + (Number(typeof f === "function" ? f(r) : r[f]) || 0), 0);
const uniq = (xs) => [...new Set(xs.filter((x) => x !== "" && x !== null && x !== undefined))];
const editable = () => S.data && !S.data.locked;
const opt = (v, label, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(label)}</option>`;

// ---------- API ----------
async function api(method, url, body) {
  const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
  return j;
}
async function loadMeta() { S.meta = await api("GET", "/api/meta"); }
async function load() {
  try { S.data = await api("GET", `/api/period/${S.period}`); }
  catch (e) { document.getElementById("main").innerHTML = `<div class="loading">${esc(e.message)}</div>`; return; }
  render();
}
async function act(method, url, body, msg) {
  try { await api(method, url, body); await load(); if (msg) toast(msg); return true; }
  catch (e) { toast(e.message, true); return false; }
}
function toast(text, bad = false) {
  const t = document.createElement("div");
  t.className = `toast ${bad ? "bad" : ""}`; t.textContent = text; t.setAttribute("role", "status");
  document.body.appendChild(t); setTimeout(() => t.remove(), bad ? 6000 : 2800);
}
const P = () => `/api/period/${S.period}`;

// ---------- shared pieces ----------
function panel(id, title, body, opts = {}) {
  if (opts.collapsible) {
    const c = S.collapsed.has(id);
    return `<section class="panel collapsible"><h2 data-action="toggle" data-panel="${id}">${c ? "▸" : "▾"} ${esc(title)}</h2>${c ? "" : body}</section>`;
  }
  return `<section class="panel"><h2>${esc(title)}</h2>${body}</section>`;
}
function exportBtn(id) { return `<button class="export secondary" data-action="export" data-id="${id}" type="button">Export (CSV)</button>`; }
function register(id, name, cols, rows) {
  EXP[id] = { name, header: cols.map((c) => c[0]), rows: rows.map((r) => cols.map((c) => c[1](r))) };
}
function downloadCSV(id) {
  const e = EXP[id]; if (!e) return;
  const q = (v) => { const s = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const text = [e.header, ...e.rows].map((r) => r.map(q).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = `${e.name}_${S.period}.csv`; a.click(); URL.revokeObjectURL(a.href);
}
function field(label, inner) { return `<div class="field"><label>${esc(label)}</label>${inner}</div>`; }
function search(key, val, ph = "Search") { return `<input type="text" id="f-${key}" data-filter="${key}" value="${esc(val)}" placeholder="${ph}">`; }
function sel(key, val, options) { return `<select id="f-${key}" data-filter="${key}">${options}</select>`; }
function bridge(t) {
  return `<div class="bridge">
    <div class="bblock"><div class="t">Vendor OpEx</div><div class="v">${money(t.vendor_opex)}</div></div><div class="bplus">+</div>
    <div class="bblock"><div class="t">Legal</div><div class="v">${money(t.legal)}</div></div><div class="bplus">+</div>
    <div class="bblock"><div class="t">Capex Projects</div><div class="v">${money(t.capex)}</div></div><div class="beq">=</div>
    <div class="bblock"><div class="t">Total Accrual</div><div class="v">${money(t.total)}</div></div></div>`;
}

// ---------- render ----------
function render() {
  const d = S.data; EXP = {};
  const active = document.activeElement; const focusId = active && active.id; const caret = active && active.selectionStart;
  document.getElementById("period-sub").innerHTML = `${esc(d.company)} · ${esc(d.period_label)} Accrual <span class="pill ${S.meta.dataset === "user" ? "warn" : "muted"}">${esc(S.meta.dataset_label)}</span>`;
  document.getElementById("runinfo").textContent = `Generated ${when(d.generated_at)} · ${S.meta.user}`;
  const openAtt = d.attention_items.filter((i) => i.period === d.period && i.status !== "Resolved").length;
  const swingsLeft = d.mom.large_swings - d.mom.large_swings_reviewed;
  const counts = { attention: openAtt, mom: swingsLeft, settings: S.meta.data_issues };
  document.getElementById("tabbar").innerHTML = TABS.map(([k, label]) =>
    `<button class="tabbtn ${S.tab === k ? "active" : ""}" role="tab" aria-selected="${S.tab === k}" data-action="tab" data-tab="${k}">${label}${counts[k] ? `<span class="cnt">${counts[k]}</span>` : ""}</button>`).join("");
  document.getElementById("lockbar").innerHTML = d.locked
    ? `<div class="lockbar">🔒 ${esc(d.period_label)} is signed off by ${esc(d.signoff.user)} on ${esc(when(d.signoff.at))}. This month is read-only.</div>` : "";
  const fn = { summary: tabSummary, opex: tabOpex, legal: tabLegal, capex: tabCapex, attention: tabAttention, mom: tabMom, je: tabJE, history: tabHistory, budget: tabBudget, ytd: tabYTD, settings: tabSettings }[S.tab];
  const main = document.getElementById("main");
  const keepScroll = [...main.querySelectorAll(".table-scroll")].map((b) => [b.scrollLeft, b.scrollTop]);
  main.innerHTML = fn(d);
  main.querySelectorAll(".table-scroll").forEach((b, i) => { if (keepScroll[i]) [b.scrollLeft, b.scrollTop] = keepScroll[i]; });
  addTopScrollbars();
  if (focusId) {
    const el = document.getElementById(focusId);
    if (el) { el.focus(); if (caret !== null && caret !== undefined && el.setSelectionRange) { try { el.setSelectionRange(caret, caret); } catch (_) { /* select */ } } }
  }
}

// A synced scrollbar above every table that is wider than its box, pinned to the top of the window,
// so you never have to scroll to the bottom of a table to move left or right.
function addTopScrollbars() {
  document.querySelectorAll("#main .hscroll-top").forEach((x) => x.remove());
  document.querySelectorAll("#main .table-scroll").forEach((box) => {
    if (box.scrollWidth <= box.clientWidth + 1) return;
    const top = document.createElement("div");
    top.className = "hscroll-top"; top.setAttribute("aria-hidden", "true");
    const inner = document.createElement("div"); inner.style.width = `${box.scrollWidth}px`;
    top.appendChild(inner); box.parentNode.insertBefore(top, box);
    // the box's own vertical scrollbar makes it narrower; widen the track so both reach the far right
    inner.style.width = `${box.scrollWidth + (top.clientWidth - box.clientWidth)}px`;
    top.scrollLeft = box.scrollLeft;
    top.addEventListener("scroll", () => { if (box.scrollLeft !== top.scrollLeft) box.scrollLeft = top.scrollLeft; });
    box.addEventListener("scroll", () => { if (top.scrollLeft !== box.scrollLeft) top.scrollLeft = box.scrollLeft; });
  });
}
window.addEventListener("resize", () => { if (S.data) addTopScrollbars(); });

// ---------- 1. Summary ----------
function tabSummary(d) {
  const ck = d.checklist; const okN = ck.items.filter((i) => i.ok).length;
  let status; let buttons = "";
  if (d.locked) status = `Signed off by <b>${esc(d.signoff.user)}</b> on ${esc(when(d.signoff.at))}.`;
  else {
    status = `${okN} of ${ck.items.length} checks complete — ${ck.can_sign_off ? "ready to sign off." : "sign-off is blocked until every item below is ticked."}`;
    buttons = S.signConfirm
      ? `<button class="btn primary" data-action="signoff-confirm" type="button">Confirm ${esc(d.period_short)} sign off and lock</button><button class="btn" data-action="signoff-cancel" type="button">Cancel</button>`
      : `<button class="btn primary" data-action="signoff-start" type="button" ${ck.can_sign_off ? "" : "disabled"}>${esc(d.period_short)} Approver Sign Off</button>`;
  }
  const checklist = `<div class="note">Before sign-off</div><ul class="checklist">${ck.items.map((i) =>
    `<li><span class="${i.ok ? "tick" : "cross"}" aria-label="${i.ok ? "done" : "not done"}">${i.ok ? "✓" : "✗"}</span><span>${esc(i.label)} <span class="sub">${esc(i.detail)}</span></span></li>`).join("")}</ul>`;
  if (d.locked && d.is_current_period) {
    const nxt = S.meta.periods.length ? monthAfter(d.period) : "";
    buttons = S.meta.dataset === "user"
      ? `<button class="btn primary" data-action="rollover" type="button">Start ${esc(monLabel(nxt))} →</button>`
      : `<span class="status-text">Start next month is available on My data (Settings tab).</span>`;
    status += ` Next: start ${esc(monLabel(nxt))}. Standing rules and this month's manual adds carry forward; then upload the new month's GL detail, legal estimates and capex tracker on the Settings tab.`;
  }
  const signoff = panel("signoff", "Accounting Reviewer Sign Off", `<div class="signoff-row"><span class="status-text">${status}</span><span class="spacer"></span>${buttons}</div>${checklist}`);

  const rows = d.components.map((c) => `<tr><td>${esc(c.label)}</td><td>${esc(c.source)}</td><td class="num">${c.lines}</td>${amt(c.amount)}<td>${esc(c.cadence)}</td>
    <td>${c.complete ? `<span class="pill confirmed">Complete</span><span class="sub">${esc(c.completed_by)} · ${esc(when(c.completed_at))}</span>` : `<span class="pill warn">Open</span>`}
    ${editable() ? ` <button class="btn small" data-action="component" data-c="${c.component}" data-v="${c.complete ? 0 : 1}" type="button">${c.complete ? "Reopen" : "Mark complete"}</button>` : ""}</td></tr>`).join("");
  register("components", "accrual_summary", [["Component", (c) => c.label], ["Source", (c) => c.source], ["Lines", (c) => c.lines], ["Amount", (c) => c.amount], ["Cadence", (c) => c.cadence], ["Status", (c) => (c.complete ? `Complete (${c.completed_by} ${c.completed_at})` : "Open")]], d.components);
  const detail = panel("detail", "Monthly OpEx Accrual Detail", `<div class="filters"><span class="spacer"></span>${exportBtn("components")}</div>
    <div class="table-scroll"><table><thead><tr><th>Component</th><th>Source</th><th>Lines</th><th>Amount</th><th>Cadence</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody><tfoot><tr><td>Total</td><td></td><td class="num">${sum(d.components, "lines")}</td><td class="num">${money(d.totals.total)}</td><td></td><td></td></tr></tfoot></table></div>
    ${d.capex.not_final ? `<div class="count-note">Capex Projects is <b>Not final</b>: ${money(d.capex.unallocated_gl)} of capex GL is not yet allocated to a project.</div>` : ""}`);

  register("scope", "gl_account_scope", [["Account", (a) => a.gl_account], ["Name", (a) => a.name], ["Kind", (a) => a.kind]], d.scope.accounts);
  const scope = panel("scope", "GL Account Scope", `<div class="filters"><span class="spacer"></span>${exportBtn("scope")}</div><div class="table-scroll"><table><thead><tr><th>Account</th><th>Name</th><th>Kind</th></tr></thead><tbody>${d.scope.accounts.map((a) => `<tr><td class="num">${a.gl_account}</td><td>${esc(a.name)}</td><td>${esc(a.kind)}</td></tr>`).join("")}</tbody></table></div>`, { collapsible: true });
  const exRows = Object.keys(d.scope.counts).map((k) => ({ reason: k, n: d.scope.counts[k], amount: d.scope.amounts[k] }));
  register("excluded", "excluded_gl", [["Reason", (r) => r.reason], ["Rows", (r) => r.n], ["Amount", (r) => r.amount]], exRows);
  const excluded = panel("excluded", "Excluded GL rows", `<div class="filters"><span class="note" style="border:0;background:none;padding:0">${d.scope.in_scope_rows} rows in scope. Every excluded row is counted with its reason.</span><span class="spacer"></span>${exportBtn("excluded")}</div><div class="table-scroll"><table><thead><tr><th>Reason</th><th>Rows</th><th>Amount</th></tr></thead><tbody>${exRows.map((r) => `<tr><td>${esc(r.reason)}</td><td class="num">${r.n}</td>${amt(r.amount)}</tr>`).join("")}</tbody></table></div>`, { collapsible: true });
  return signoff + panel("bridge", "Monthly OpEx Accrual Summary", bridge(d.totals)) + detail + scope + excluded + panel("overview", "Overview", `<div class="prose">${OVERVIEW}</div>`, { collapsible: true });
}

// ---------- 2. Vendor OpEx ----------
const TYPE_SPECIAL = { __manual: "Manual add", __ovr: "Overridden only", __input: "Needs input" };
function opexRows(d) {
  const f = S.f.opex; const q = f.q.toLowerCase();
  let rows = d.vendor_opex.lines.filter((l) => {
    if (q && !`${l.vendor_name} ${l.vendor_id} ${l.gl_account} ${l.owner} ${l.vendor_type}`.toLowerCase().includes(q)) return false;
    if (f.vendor && l.vendor_id !== f.vendor) return false;
    if (f.acct && String(l.gl_account) !== f.acct) return false;
    if (f.type === "__manual") return l.line_type !== "roster";
    if (f.type === "__ovr") return !!l.override;
    if (f.type === "__input") return l.needs_input;
    if (f.type && l.vendor_type !== f.type) return false;
    return true;
  });
  if (S.sort.key) {
    const k = S.sort.key;
    rows = [...rows].sort((a, b) => (String(a[k]).localeCompare(String(b[k]), undefined, { numeric: true })) * S.sort.dir);
  }
  return rows;
}
function appliedNote(l) {
  if (l.accrual_rule) return `<span class="sub">Accrual rule: ${esc(l.accrual_rule)}</span>`;
  const s = l.standing; if (!s) return "";
  const pillCls = s.status === "Review" ? "bad" : s.status === "Preview" ? "muted" : "confirmed";
  return `<span class="sub">${s.active ? "Standing" : "Preview"}: ${esc(s.rule)} → ${money(s.amount)} <span class="pill ${pillCls}">${esc(s.status)}</span></span><span class="sub">${esc(s.basis)}</span>`;
}
function overrideCell(l) {
  if (l.line_type === "manual") return `<b>Manual add</b><span class="sub">${esc(l.manual.explanation)} · ${esc(l.manual.user || "")} ${esc(when(l.manual.at))}</span>${editable() ? ` <button class="btn small danger" data-action="manual-delete" data-id="${l.manual.id}" type="button">Delete</button>` : ""}`;
  if (l.line_type === "carried" && !l.override) return `<b>Carried manual add</b><span class="sub">${esc(l.manual.explanation)}</span>${editable() ? ` <button class="btn small" data-action="ovr-open" data-key="${esc(l.key)}" type="button">Override</button>` : ""}`;
  if (l.override) return `<b class="num">${money(l.override.amount)}</b><span class="sub">${esc(l.override.explanation)} · ${esc(l.override.user)} ${esc(when(l.override.at))}</span>${editable() ? ` <button class="btn small" data-action="ovr-open" data-key="${esc(l.key)}" type="button">Edit</button>` : ""}`;
  return editable() ? `<button class="btn small" data-action="ovr-open" data-key="${esc(l.key)}" type="button">Override</button>` : "";
}
function tabOpex(d) {
  const f = S.f.opex; const rows = opexRows(d); const months = d.vendor_opex.month_columns; const all = d.vendor_opex.lines;
  const vendors = uniq(all.map((l) => l.vendor_id)).map((v) => [v, all.find((l) => l.vendor_id === v).vendor_name]).sort((a, b) => a[1].localeCompare(b[1]));
  const accts = uniq(all.map((l) => l.gl_account)).sort();
  const types = uniq(all.map((l) => l.vendor_type)).sort();
  const filters = `<div class="filters">
    ${field("Search", search("opex.q", f.q, "Vendor, ID, account, owner"))}
    ${field("Vendor", sel("opex.vendor", f.vendor, opt("", "All vendors", f.vendor) + vendors.map(([v, n]) => opt(v, n, f.vendor)).join("")))}
    ${field("Account", sel("opex.acct", f.acct, opt("", "All accounts", f.acct) + accts.map((a) => opt(a, a, f.acct)).join("")))}
    ${field("Type", sel("opex.type", f.type, opt("", "All types", f.type) + Object.entries(TYPE_SPECIAL).map(([k, v]) => opt(k, v, f.type)).join("") + types.map((t) => opt(t, t, f.type)).join("")))}
    <span class="spacer"></span>
    ${editable() && d.is_current_period ? `<button class="export" data-action="manual-open" type="button">+ Add manual accrual</button>` : ""}
    ${exportBtn("opex")}</div>`;
  const sortTh = (k, label, cls = "") => `<th class="sortable ${cls}" data-action="sort" data-key="${k}">${label}${S.sort.key === k ? (S.sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`;
  const head = `<tr>${sortTh("vendor_name", "Vendor", "sticky-col")}${sortTh("gl_account", "Account")}${sortTh("vendor_type", "Type")}${sortTh("owner", "Owner")}
    <th>Annual Budget</th><th>Budget YTD</th><th>GL Total YTD</th><th>Spend YTD</th><th>Prior-Year Liab. Remaining</th><th>Calculated Accrual</th><th>Override</th><th>Final Accrual</th>
    ${months.map((m) => `<th>${monLabel(m)}</th>`).join("")}<th>Prior-year service (excluded)</th><th>Prepaid (included)</th><th>Billed for after cutoff (included)</th><th>Next-year portion of prepaid (excluded)</th></tr>`;
  const body = rows.map((l) => {
    const cls = l.line_type !== "roster" ? "madd-row" : l.override ? "ovr-row" : "";
    const liab = l.liability_opening !== null ? `<span class="sub">${money(l.liability_opening)} − ${money(l.liability_prior_year_bills)}</span>` : "";
    return `<tr class="${cls}">
      <td class="sticky-col"><span class="vendor-name">${esc(l.vendor_name)}</span><span class="sub vendor-id">${esc(l.vendor_id)}</span></td>
      <td class="num">${l.gl_account}<span class="sub">${esc(l.gl_account_name)}</span></td><td>${esc(l.vendor_type)}</td>
      <td>${l.owner ? esc(l.owner) : `<span class="pill warn">WIP</span>`}</td>
      ${amt(l.annual_budget)}<td class="num amt">${money(l.budget_ytd)}${l.budget_source && l.budget_source !== "budget" ? `<span class="sub">${esc(l.budget_source)}</span>` : ""}</td>
      ${amt(l.gl_total_ytd)}${amt(l.spend_ytd)}<td class="num amt">${money(l.liability_remaining)}${liab}</td>
      <td class="num amt"><span class="${l.override ? "ovr-struck" : ""}">${money(l.formula_accrual)}</span>${appliedNote(l)}</td>
      <td class="wrap">${overrideCell(l)}</td>${amt(l.final_accrual, "accrual")}
      ${months.map((m) => amt(l.buckets[m] ?? null)).join("")}
      ${amt(l.prior_year_service)}${amt(l.prepaid_included)}${amt(l.after_cutoff)}${amt(l.prepaid_next_year)}</tr>`;
  }).join("");
  const foot = `<tr><td class="sticky-col">Total</td><td></td><td></td><td></td>${["annual_budget", "budget_ytd", "gl_total_ytd", "spend_ytd", "liability_remaining", "formula_accrual"].map((k) => `<td class="num">${money(sum(rows, k))}</td>`).join("")}<td></td><td class="num">${money(sum(rows, "final_accrual"))}</td>
    ${months.map((m) => `<td class="num">${money(sum(rows, (l) => l.buckets[m]))}</td>`).join("")}${["prior_year_service", "prepaid_included", "after_cutoff", "prepaid_next_year"].map((k) => `<td class="num">${money(sum(rows, k))}</td>`).join("")}</tr>`;
  register("opex", "vendor_opex", [
    ["Vendor", (l) => l.vendor_name], ["Vendor ID", (l) => l.vendor_id], ["Account", (l) => l.gl_account], ["Type", (l) => l.vendor_type], ["Owner", (l) => l.owner],
    ["Annual Budget", (l) => l.annual_budget], ["Budget YTD", (l) => l.budget_ytd], ["GL Total YTD", (l) => l.gl_total_ytd], ["Spend YTD", (l) => l.spend_ytd],
    ["Prior-Year Liability Remaining", (l) => l.liability_remaining], ["Calculated Accrual", (l) => l.formula_accrual], ["Applied By", (l) => l.applied_by],
    ["Standing Rule", (l) => (l.standing ? `${l.standing.rule} (${l.standing.status})` : "")], ["Override", (l) => (l.override ? l.override.amount : "")],
    ["Override Explanation", (l) => (l.override ? l.override.explanation : l.manual ? l.manual.explanation : "")], ["Final Accrual", (l) => l.final_accrual],
    ...months.map((m) => [monLabel(m), (l) => l.buckets[m] ?? ""]),
    ["Prior-year service (excluded)", (l) => l.prior_year_service], ["Prepaid (included)", (l) => l.prepaid_included],
    ["Billed after cutoff (included)", (l) => l.after_cutoff], ["Next-year prepaid (excluded)", (l) => l.prepaid_next_year], ["Dims source", (l) => l.dims.source],
  ], rows);
  const note = `<div class="note">Calculated accrual = MAX(Budget YTD + Prior-Year Liability Remaining − Spend YTD, $0). Budget YTD = annual budget × ${d.months_elapsed} ÷ 12. Spend YTD = service months Jan–${MON[d.months_elapsed - 1]} + prepaid current-year share + bills for service after the cutoff. Standing rules, accrual rules and overrides can replace the calculated value; the final accrual is what books.</div>`;
  return panel("opex", `Vendor OpEx — ${d.period_label}`, note + filters + `<div class="table-scroll"><table><thead>${head}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div><div class="count-note">Showing ${rows.length} of ${all.length} lines · ${all.filter((l) => l.final_accrual > 0).length} lines accrue · total ${money(d.vendor_opex.total)}</div>`);
}

// ---------- 3. Legal ----------
const LEGAL_FIELDS = ["amount", "gl", "item", "customer", "project", "dept", "location", "note"];
function tabLegal(d) {
  const ed = editable();
  const add = S.ui.legalAdd ? `<div class="filters" style="border-top:1px solid var(--border)">
      ${["vendor", "vendor_id", "amount", "gl", "item", "customer", "project", "dept", "location", "note"].map((k) =>
        field(k.replace("_", " "), `<input type="text" id="la-${k}" value="${esc(k in S.meta.legal_defaults ? S.meta.legal_defaults[k] : "")}">`)).join("")}
      <button class="export" data-action="legal-add-save" type="button">Add vendor</button><button class="btn" data-action="legal-add-toggle" type="button">Cancel</button></div>` : "";
  const rows = d.legal.rows.map((r) => {
    const dirty = S.legalDirty[r.vendor_id] || {};
    const val = (k) => (k in dirty ? dirty[k] : r[k] ?? "");
    const input = (k) => `<td><input type="text" class="${k === "amount" ? "amt-in" : ""}" data-legal="${esc(r.vendor_id)}" data-field="${k}" value="${esc(val(k))}" ${ed ? "" : "disabled"} aria-label="${k}"></td>`;
    const amountCell = r.splits ? `<td class="num amt">${money(r.total)}<span class="sub">split · ${r.splits.length} lines</span></td>` : input("amount");
    return `<tr class="${Object.keys(dirty).length ? "row-dirty" : ""}" data-row="${esc(r.vendor_id)}">
      <td><span class="vendor-name">${esc(r.vendor)}</span>${r.added ? `<span class="sub">added this month</span>` : ""}</td><td>${esc(r.vendor_id)}</td>
      ${amountCell}${r.splits ? `<td class="num">${r.splits.map((s) => s.gl).join(", ")}</td><td>${esc(r.splits.map((s) => s.item).join(", "))}</td>` : input("gl") + input("item")}
      ${input("customer")}${input("project")}${input("dept")}${input("location")}${input("note")}
      <td>${ed ? `<button class="btn small primary" data-action="legal-save" data-vid="${esc(r.vendor_id)}" type="button">Save</button> <button class="btn small" data-action="legal-split" data-vid="${esc(r.vendor_id)}" type="button">Split</button>` : ""}</td></tr>`;
  }).join("");
  register("legal", "legal", [["Vendor", (r) => r.vendor], ["Vendor ID", (r) => r.vendor_id], ["Amount", (r) => r.total], ["GL", (r) => (r.splits ? r.splits.map((s) => s.gl).join(" / ") : r.gl)], ["Item", (r) => r.item], ["Customer", (r) => r.customer], ["Project", (r) => r.project], ["Dept", (r) => r.dept], ["Location", (r) => r.location], ["Backup note", (r) => r.note], ["Split lines", (r) => (r.splits ? r.splits.length : "")]], d.legal.rows);
  const body = `<div class="note">Law firm estimates for work performed but not yet billed. Edit any cell and Save; the row stays yellow until saved. Split one firm across GL lines with Split — each line becomes its own JE debit. Reading the firm's backup documents with AI is not part of this rebuild.</div>
    <div class="filters"><span class="spacer"></span>${ed ? `<button class="export" data-action="legal-add-toggle" type="button">+ Add vendor</button>` : ""}${exportBtn("legal")}</div>${add}
    <div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Vendor ID</th><th>Amount</th><th>GL</th><th>Item</th><th>Customer</th><th>Project</th><th>Dept</th><th>Location</th><th>Backup note</th><th>Save / Split</th></tr></thead>
    <tbody>${rows}</tbody><tfoot><tr><td>Total</td><td></td><td class="num">${money(d.legal.total)}</td><td colspan="8"></td></tr></tfoot></table></div>`;
  return panel("legal", `Legal — ${d.period_label}`, body);
}

// ---------- 4. Capex ----------
function tabCapex(d) {
  const c = d.capex; const f = S.f.capex; const q = f.q.toLowerCase();
  const lines = c.lines.filter((l) => (!q || `${l.deal} ${l.vendor} ${l.area} ${l.project_id}`.toLowerCase().includes(q)) && (!f.deal || l.deal === f.deal) && (!f.vendor || l.vendor_id === f.vendor));
  const groups = Object.fromEntries(c.groups.map((g) => [`${g.project_id}|${g.vendor_id}`, g]));
  const deals = uniq(c.lines.map((l) => l.deal));
  let body = "";
  for (const deal of deals) {
    const dl = lines.filter((l) => l.deal === deal).sort((a, b) => a.vendor_id.localeCompare(b.vendor_id) || a.line_no - b.line_no);
    if (!dl.length) continue;
    dl.forEach((l, i) => {
      const gk = `${l.project_id}|${l.vendor_id}`; const first = i === 0 || `${dl[i - 1].project_id}|${dl[i - 1].vendor_id}` !== gk;
      const span = dl.filter((x) => `${x.project_id}|${x.vendor_id}` === gk).length; const g = groups[gk];
      body += `<tr class="${i === 0 ? "deal-start" : ""}"><td>${i === 0 ? `<b>${esc(deal)}</b><span class="sub">${esc(l.project_id)}</span>` : ""}</td>
        <td><span class="vendor-name">${esc(l.vendor)}</span><span class="sub vendor-id">${esc(l.vendor_id)}</span></td><td>${esc(l.area)}</td>
        ${amt(l.cost)}<td>${esc(l.work_request_date || "")}</td><td class="num">${l.pct_complete === null ? "" : `${l.pct_complete}%`}</td>
        <td>${l.fully_complete ? "Yes" : "No"}</td><td>${l.placed_in_service ? "Yes" : "No"}</td>${amt(l.invoiced_to_date)}${amt(l.accrual)}
        ${first ? `<td rowspan="${span}" class="num amt accrual">${money(g.je_amount)}${g.invoiced_beyond_earned ? `<span class="sub neg">Invoiced beyond earned (${money(g.net)}) → $0</span>` : ""}</td>` : ""}</tr>`;
    });
    const dt = d.capex.deals.find((x) => x.deal === deal);
    body += `<tr class="deal-total"><td>Deal Total</td><td></td><td></td>${amt(dt.cost)}<td colspan="5">Budget ${money(dt.budget)} · ${esc(dt.status)}</td><td></td><td class="num">${money(sum(c.groups.filter((g) => g.deal === deal), "je_amount"))}</td></tr>`;
  }
  register("capex", "capex_projects", [["Deal", (l) => l.deal], ["Project", (l) => l.project_id], ["Vendor", (l) => l.vendor], ["Vendor ID", (l) => l.vendor_id], ["Area", (l) => l.area], ["Cost", (l) => l.cost], ["Work Req. Date", (l) => l.work_request_date], ["% Compl.", (l) => l.pct_complete], ["Fully Complete", (l) => (l.fully_complete ? "Yes" : "No")], ["Placed in Service", (l) => (l.placed_in_service ? "Yes" : "No")], ["Invoiced to Date", (l) => l.invoiced_to_date], ["Vendor Area Total", (l) => l.accrual], ["Vendor Accrual Amount (JE)", (l) => groups[`${l.project_id}|${l.vendor_id}`].je_amount]], lines);
  const vendors = uniq(c.lines.map((l) => l.vendor_id)).map((v) => [v, c.lines.find((l) => l.vendor_id === v).vendor]);
  const pctDone = c.lines.length ? Math.round((100 * c.complete_lines) / c.lines.length) : 0;
  const status = `<div class="progress" style="border-top:0">Completion: ${c.complete_lines} of ${c.lines.length} lines fully complete<div class="bar"><i style="width:${pctDone}%"></i></div></div><div class="note">${c.complete_lines} of ${c.lines.length} lines fully complete · ${c.blank_lines} line(s) with blank cost or % accrue $0 · Capex accrual ${money(c.total)} · <b>${c.not_final ? "Not final (unallocated GL)" : "Final"}</b>. Line accrual = Cost × % Complete − Invoiced to Date; the JE nets by project + vendor and never books below $0. Read-only.</div>`;
  const filters = `<div class="filters">${field("Search", search("capex.q", f.q))}${field("Deal", sel("capex.deal", f.deal, opt("", "All deals", f.deal) + deals.map((x) => opt(x, x, f.deal)).join("")))}${field("Vendor", sel("capex.vendor", f.vendor, opt("", "All vendors", f.vendor) + vendors.map(([v, n]) => opt(v, n, f.vendor)).join("")))}<span class="spacer"></span>${exportBtn("capex")}</div>`;
  const table = `<div class="table-scroll"><table><thead><tr><th>Deal</th><th>Vendor</th><th>Area</th><th>Cost</th><th>Work Req. Date</th><th>% Compl.</th><th>Fully Complete</th><th>Placed in Service</th><th>Invoiced to Date</th><th>Vendor Area Total</th><th>Vendor Accrual Amount (JE)</th></tr></thead><tbody>${body}</tbody>
    <tfoot><tr><td>Total</td><td></td><td></td><td class="num">${money(sum(lines, "cost"))}</td><td colspan="6"></td><td class="num">${money(c.total)}</td></tr></tfoot></table></div>`;
  const att = `<div class="bridge"><div class="bblock"><div class="t">Lines needing attention</div><div class="v">${c.needs_attention_count}</div></div>
    <div class="bblock"><div class="t">Total amount</div><div class="v">${money(c.needs_attention_total)}</div></div>
    <div class="bblock"><div class="t">Unallocated GL (not in accrual)</div><div class="v">${money(c.unallocated_gl)}</div></div></div>`;
  return panel("capex", `Capex Projects — ${d.period_label}`, status + filters + table) + panel("capex-att", "Needs attention", att);
}

// ---------- 5. Needs Attention ----------
function lineFor(vid, acct) { return S.data.vendor_opex.lines.find((l) => l.vendor_id === vid && String(l.gl_account) === String(acct)); }
function tabAttention(d) {
  const st = d.standing;
  const stRows = st.table.map((t) => {
    const pc = t.status === "Review" ? "bad" : t.status === "Reviewed" || t.status === "Auto-applied" ? "confirmed" : "muted";
    return `<tr class="${t.status === "Review" ? "hl" : ""}"><td><span class="vendor-name">${esc(t.vendor_name)}</span><span class="sub vendor-id">${esc(t.vendor_id)}</span></td><td class="num">${t.gl_account}</td>
      <td>${esc(t.rule)}${t.note ? `<span class="sub">${esc(t.note)}</span>` : ""}</td><td class="wrap">${esc(t.basis)}${t.flags.map((fl) => `<span class="sub neg">⚠ ${esc(fl.message)}</span>`).join("")}${t.superseded ? `<span class="sub">Superseded by a current-month manual add</span>` : ""}</td>
      ${amt(t.amount)}<td><span class="pill ${pc}">${esc(t.status)}</span></td>
      <td>${t.needs_confirm && t.status === "Review" && editable() ? `<button class="btn small primary" data-action="standing-confirm" data-key="${esc(t.key)}" type="button">Confirm</button>` : ""}</td></tr>`;
  }).join("");
  register("standing", "standing_rules", [["Vendor", (t) => t.vendor_name], ["Vendor ID", (t) => t.vendor_id], ["Acct", (t) => t.gl_account], ["Rule", (t) => t.rule], ["Basis", (t) => t.basis], ["Flags", (t) => t.flags.map((x) => x.message).join(" | ")], ["Amount", (t) => t.amount], ["Review", (t) => t.status]], st.table);
  const standing = panel("standing", `Standing rules carried forward (baseline ${st.baseline_month || "—"}${st.active ? ", applied this month" : ", preview only"})`,
    `<div class="filters"><span class="spacer"></span>${exportBtn("standing")}</div><div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Acct</th><th>Rule</th><th>Basis</th><th>Amount</th><th>Review</th><th>Confirm</th></tr></thead><tbody>${stRows}</tbody></table></div>`, { collapsible: true });

  const f = S.f.att; const items = d.attention_items; const q = f.q.toLowerCase();
  const per = f.period || d.period;
  const inPeriod = items.filter((i) => per === "all" || i.period === per);
  const shown = inPeriod.filter((i) => (f.status === "active" ? i.status !== "Resolved" : !f.status || i.status === f.status)
    && (!f.category || i.category === f.category) && (!q || `${i.vendor} ${i.vendor_id} ${i.account} ${i.summary} ${i.detail}`.toLowerCase().includes(q)));
  const open = inPeriod.filter((i) => i.status !== "Resolved");
  const chips = `<div class="chips"><div class="chip"><b>${open.length}</b>open</div><div class="chip"><b>${open.filter((i) => !i.assignee).length}</b>unassigned</div><div class="chip"><b>${money(sum(open, "amount"))}</b>open amount</div><div class="chip ok"><b>${inPeriod.length - open.length}</b>resolved</div></div>`;
  const cats = uniq(items.map((i) => i.category)); const periods = uniq(items.map((i) => i.period)).sort().reverse();
  const filters = `<div class="filters">${field("Status", sel("att.status", f.status, opt("active", "Open + In review", f.status) + opt("", "All", f.status) + ["Open", "In review", "Resolved"].map((s) => opt(s, s, f.status)).join("")))}
    ${field("Category", sel("att.category", f.category, opt("", "All", f.category) + cats.map((c) => opt(c, c, f.category)).join("")))}
    ${field("Period", sel("att.period", per, periods.map((p) => opt(p, p, per)).join("") + opt("all", "All periods", per)))}
    ${field("Search", search("att.q", f.q))}<span class="spacer"></span>${editable() ? `<button class="export" data-action="att-add-toggle" type="button">+ Add item</button>` : ""}${exportBtn("attention")}</div>`;
  const add = S.ui.attAdd ? `<div class="filters" style="border-top:1px solid var(--border)">${[["category", "Category"], ["vendor", "Vendor"], ["vendor_id", "Vendor ID"], ["account", "Account"], ["amount", "Amount"], ["summary", "Summary"], ["detail", "Detail"], ["proposed", "Proposed"], ["assignee", "Assignee"]].map(([k, l]) => field(l, `<input type="text" id="aa-${k}">`)).join("")}
    <button class="export" data-action="att-add-save" type="button">Add item</button><button class="btn" data-action="att-add-toggle" type="button">Cancel</button></div>` : "";
  const rows = shown.map((i) => {
    const ln = i.vendor_id && i.account ? lineFor(i.vendor_id, i.account) : null;
    const action = !editable() || i.period !== d.period ? "" : ln ? `<button class="btn small" data-action="ovr-open" data-key="${esc(ln.key)}" type="button">Override accrual</button>`
      : i.vendor_id ? `<button class="btn small" data-action="manual-open" data-vendor="${esc(i.vendor)}" data-vid="${esc(i.vendor_id)}" data-acct="${esc(i.account)}" type="button">+ Add accrual</button>` : "";
    return `<tr><td>${esc(i.category)}<span class="sub">${esc(i.period)} · ${esc(i.source)}</span></td>
      <td><span class="vendor-name">${esc(i.vendor || "—")}</span><span class="sub">${esc(i.vendor_id)} ${esc(i.account)}</span></td>${amt(i.amount)}
      <td class="wrap"><b>${esc(i.summary)}</b>${i.detail || i.proposed ? `<details><summary>Details</summary><span class="sub">${esc(i.detail)}</span>${i.proposed ? `<span class="sub">Proposed: ${esc(i.proposed)}</span>` : ""}</details>` : ""} ${action}</td>
      <td><input type="text" id="att-as-${i.id}" value="${esc(i.assignee)}" placeholder="Assignee" aria-label="Assignee"><select id="att-st-${i.id}" aria-label="Status">${["Open", "In review", "Resolved"].map((s) => opt(s, s, i.status)).join("")}</select></td>
      <td class="wrap"><textarea id="att-res-${i.id}" aria-label="Resolution" placeholder="Resolution">${esc(i.resolution)}</textarea>${editable() || i.period !== d.period ? `<button class="btn small primary" data-action="att-save" data-id="${i.id}" data-period="${esc(i.period)}" type="button">Save</button>` : ""}</td></tr>`;
  }).join("");
  register("attention", "needs_attention", [["Category", (i) => i.category], ["Period", (i) => i.period], ["Vendor", (i) => i.vendor], ["Vendor ID", (i) => i.vendor_id], ["Account", (i) => i.account], ["Amount", (i) => i.amount], ["Summary", (i) => i.summary], ["Detail", (i) => i.detail], ["Proposed", (i) => i.proposed], ["Assignee", (i) => i.assignee], ["Status", (i) => i.status], ["Resolution", (i) => i.resolution]], shown);
  return standing + panel("att", "Needs Attention", chips + filters + add + `<div class="table-scroll"><table><thead><tr><th>Item</th><th>Vendor / Account</th><th>Amount</th><th>Issue</th><th>Owner / Status</th><th>Resolution</th></tr></thead><tbody>${rows || `<tr><td colspan="6">Nothing matches these filters.</td></tr>`}</tbody></table></div><div class="count-note">Showing ${shown.length} of ${inPeriod.length} items</div>`);
}

// ---------- 6. MoM ----------
function tabMom(d) {
  const m = d.mom; const t = m.totals; const f = S.f.mom; const q = f.q.toLowerCase();
  const kpis = `<div class="kpis five" style="margin:18px">${[["Prior Total", t.prior_total], ["Current GL", t.current_gl], ["Current Accrual", t.current_accrual], ["Current Total", t.current_total], ["MoM $", t.mom]].map(([l, v]) => `<div class="kpi"><div class="label">${l}</div><div class="value ${v < 0 ? "neg" : ""}">${money(v)}</div></div>`).join("")}</div>`;
  const prog = m.large_swings ? Math.round((100 * m.large_swings_reviewed) / m.large_swings) : 100;
  const progress = `<div class="progress">${m.large_swings_reviewed} of ${m.large_swings} large swings reviewed (≥ $10K and ≥ 25%)<div class="bar"><i style="width:${prog}%"></i></div></div>`;
  const keep = (r) => (!f.acct || String(r.gl_account) === f.acct) && (!q || `${r.vendor} ${r.vendor_id} ${r.why}`.toLowerCase().includes(q))
    && (!f.driver || r.driver === f.driver) && (!f.att || (f.att === "yes") === !!r.needs_attention) && (!f.rev || (f.rev === "yes") === r.reviewed)
    && (!f.size || (f.size === "large" ? r.large_swing : Math.abs(r.mom) >= 1000)) && (!f.dir || (f.dir === "up" ? r.mom > 0 : r.mom < 0));
  const rowsByKey = Object.fromEntries(m.rows.map((r) => [r.key, r]));
  const shown = m.rows.filter(keep);
  let body = "";
  for (const a of m.accounts) {
    const rs = a.rows.map((k) => rowsByKey[k]).filter(keep);
    if (!rs.length) continue;
    body += `<tr class="group-head"><td colspan="11">${a.gl_account} · ${esc(a.account_name)}</td></tr>`;
    body += rs.map((r) => {
      const ln = S.data.vendor_opex.lines.find((l) => l.key === r.key);
      return `<tr class="${r.large_swing && !r.reviewed ? "hl" : ""}"><td><span class="vendor-name">${esc(r.vendor)}</span><span class="sub vendor-id">${esc(r.vendor_id)}</span></td>
        ${amt(r.prior_total)}${amt(r.current_gl)}${amt(r.current_accrual)}${amt(r.current_total)}
        <td class="num amt ${r.mom < 0 ? "neg" : ""}">${money(r.mom)}${r.large_swing ? ` <span class="pill bad">Large</span>` : ""}</td><td class="num">${pct(r.pct)}</td>
        <td class="wrap"><span class="pill muted">${esc(r.driver)}</span><span class="sub">${esc(r.why)}</span></td>
        <td>${r.needs_attention ? `<span class="pill warn">Open item</span>` : ""}</td>
        <td>${ln && editable() ? `<button class="btn small" data-action="ovr-open" data-key="${esc(ln.key)}" type="button">${ln.override ? "Edit override" : "Override"}</button>` : ""}</td>
        <td><label><input type="checkbox" data-review="${esc(r.key)}" ${r.reviewed ? "checked" : ""} ${editable() ? "" : "disabled"}> Reviewed</label>${r.reviewed ? `<span class="sub">${esc(r.reviewed_by)} · ${esc(when(r.reviewed_at))}</span>` : ""}</td></tr>`;
    }).join("");
    body += `<tr class="subtotal"><td>Account total</td>${amt(a.prior_total)}${amt(a.current_gl)}${amt(a.current_accrual)}${amt(a.current_total)}${amt(a.mom)}<td class="num">${pct(a.pct)}</td><td class="wrap" colspan="4">${esc(a.why)}</td></tr>`;
  }
  const accts = m.accounts.map((a) => opt(a.gl_account, `${a.gl_account} ${a.account_name}`, f.acct)).join("");
  const drivers = uniq(m.rows.map((r) => r.driver)).map((x) => opt(x, x, f.driver)).join("");
  const yn = (k) => sel(`mom.${k}`, f[k], opt("", "All", f[k]) + opt("yes", "Yes", f[k]) + opt("no", "No", f[k]));
  const filters = `<div class="filters">${field("Account", sel("mom.acct", f.acct, opt("", "All accounts", f.acct) + accts))}${field("Search", search("mom.q", f.q))}
    ${field("Driver", sel("mom.driver", f.driver, opt("", "All drivers", f.driver) + drivers))}${field("Needs Attention", yn("att"))}${field("Reviewed", yn("rev"))}
    ${field("MoM size", sel("mom.size", f.size, opt("", "All", f.size) + opt("large", "Large swings only", f.size) + opt("1k", "≥ $1,000", f.size)))}
    ${field("Direction", sel("mom.dir", f.dir, opt("", "All", f.dir) + opt("up", "Up", f.dir) + opt("down", "Down", f.dir)))}<span class="spacer"></span>${exportBtn("mom")}</div>`;
  register("mom", "mom_review", [["Account", (r) => r.gl_account], ["Vendor", (r) => r.vendor], ["Vendor ID", (r) => r.vendor_id], ["Prior Total", (r) => r.prior_total], ["Current GL", (r) => r.current_gl], ["Current Accrual", (r) => r.current_accrual], ["Current Total", (r) => r.current_total], ["MoM $", (r) => r.mom], ["MoM %", (r) => (r.pct === null ? "" : r.pct)], ["Driver", (r) => r.driver], ["Why", (r) => r.why], ["Large swing", (r) => (r.large_swing ? "Yes" : "")], ["Reviewed", (r) => (r.reviewed ? `${r.reviewed_by} ${r.reviewed_at}` : "")]], shown);
  const note = `<div class="note">Prior total = last month's bills + accrual booked − earlier reversal. Current total = this month's bills − last month's accrual reversed + this month's accrual. Last month's figures come from: <b>${esc(d.prior_source || "uploaded files")}</b>.</div>`;
  return panel("mom", `MoM Review — ${d.period_label}`, kpis + progress + note + filters + `<div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Prior Total</th><th>Current GL</th><th>Current Accrual</th><th>Current Total</th><th>MoM $</th><th>MoM %</th><th>Why</th><th>Needs Attention</th><th>Accrual action</th><th>Reviewed</th></tr></thead><tbody>${body}</tbody></table></div><div class="count-note">Showing ${shown.length} of ${m.rows.length} vendor + account lines</div>`);
}

// ---------- 7. Journal Entry ----------
function tabJE(d) {
  const je = d.je; const f = S.f.je; const h = je.header;
  const chips = `<div class="chips">${je.checks.map((c) => `<div class="chip ${c.ok ? "ok" : "bad"}"><b>${c.ok ? "✓" : "⚠"} ${esc(c.name)}</b>${c.ok ? money(c.actual) : `JE ${money(c.actual)} vs ${money(c.expected)} (diff ${money(c.difference)})`}</div>`).join("")}</div>`;
  const lines = je.lines.filter((l) => !f.section || l.section === f.section);
  const rows = lines.map((l) => `<tr class="${l.side === "credit" ? "je-credit" : ""}"><td>${esc(h.date)}</td><td>${esc(l.memo)}<span class="sub">${esc(l.section)}</span></td><td class="num">${l.acct}</td><td>${esc(l.acct_name)}</td>
    <td>${l.dept ? esc(l.dept) : `<span class="pill bad">missing</span>`}<span class="sub">${esc(l.dept_name)}</span></td><td>${l.location ? esc(l.location) : `<span class="pill bad">missing</span>`}<span class="sub">${esc(l.location_name)}</span></td>
    <td>${esc(l.project)}</td><td>${esc(l.customer)}</td><td>${esc(l.vendor_id)}<span class="sub">${esc(l.vendor_name)}</span></td><td>${esc(l.item)}</td>
    ${l.debit ? amt(l.debit) : "<td></td>"}${l.credit ? amt(l.credit) : "<td></td>"}<td>${esc(l.dims_source)}</td></tr>`).join("");
  register("je", "journal_entry", [["Line", (l) => l.line_no], ["Section", (l) => l.section], ["Date", () => h.date], ["Memo", (l) => l.memo], ["Account", (l) => l.acct], ["Account desc", (l) => l.acct_name], ["Department", (l) => l.dept], ["Location", (l) => l.location], ["Project", (l) => l.project], ["Customer", (l) => l.customer], ["Vendor", (l) => l.vendor_id], ["Item", (l) => l.item], ["Debit", (l) => l.debit || ""], ["Credit", (l) => l.credit || ""], ["Dims source", (l) => l.dims_source]], lines);
  const filters = `<div class="filters">${field("Section", sel("je.section", f.section, opt("", "All sections", f.section) + ["Vendor OpEx", "Legal", "Capex Projects"].map((s) => opt(s, s, f.section)).join("")))}<span class="spacer"></span>
    <a class="export secondary" href="${P()}/backup.xlsx">Download JE Backup</a> <a class="export" href="${P()}/je.csv">Download JE Upload (CSV)</a> ${exportBtn("je")}</div>`;
  const note = `<div class="note"><b>${esc(h.memo)}</b> · dated ${esc(h.date)} · auto-reverses ${esc(h.reverse_date)} · journal ${esc(h.journal)} · reference ${esc(h.reference)} · ${je.lines.length} lines</div>`;
  return panel("je", "Journal Entry", note + chips + filters + `<div class="table-scroll"><table><thead><tr><th>Date</th><th>Memo</th><th>Account no.</th><th>Account desc</th><th>Department</th><th>Location</th><th>Project</th><th>Customer</th><th>Vendor</th><th>Item</th><th>Debit</th><th>Credit</th><th>Dims source</th></tr></thead><tbody>${rows}</tbody>
    <tfoot><tr><td>Total</td><td colspan="9"></td><td class="num">${money(sum(lines, "debit"))}</td><td class="num">${money(sum(lines, "credit"))}</td><td></td></tr></tfoot></table></div>`);
}

// ---------- 8. History ----------
function tabHistory() {
  const so = S.meta.signoffs;
  const btns = so.length ? so.map((s) => `<button class="btn ${S.historyPeriod === s.period ? "primary" : ""}" data-action="history-open" data-p="${s.period}" type="button">${monLabel(s.period)} Accrual · ${money(s.total)}</button>`).join("") : `<span class="status-text">No months signed off yet.</span>`;
  let detail = "";
  const h = S.history;
  if (h) {
    const snap = h.snapshot; const p = h.period;
    const opex = snap.vendor_opex.filter((l) => l.final_accrual > 0);
    register("h-opex", `history_vendor_opex_${p}`, [["Vendor", (l) => l.vendor_name], ["Account", (l) => l.gl_account], ["Calculated", (l) => l.formula_accrual], ["Final", (l) => l.final_accrual], ["Applied by", (l) => l.applied_by]], opex);
    register("h-je", `history_je_${p}`, [["Line", (l) => l.line_no], ["Section", (l) => l.section], ["Account", (l) => l.acct], ["Dept", (l) => l.dept], ["Location", (l) => l.location], ["Vendor", (l) => l.vendor_id], ["Debit", (l) => l.debit || ""], ["Credit", (l) => l.credit || ""]], snap.je.lines);
    detail = panel("h-detail", `${snap.summary.period_label} — signed off by ${h.user} on ${when(h.at)}`,
      `<div class="filters"><span class="status-text">Read-only snapshot saved at sign-off.</span><span class="spacer"></span><a class="export secondary" href="/api/period/${p}/backup.xlsx">Download JE Backup</a> <a class="export" href="/api/period/${p}/je.csv">Download JE Upload (CSV)</a></div>${bridge(snap.summary.totals)}`)
      + panel("h-opex", "Vendor OpEx (accruing lines)", `<div class="filters"><span class="spacer"></span>${exportBtn("h-opex")}</div><div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Account</th><th>Calculated</th><th>Final</th><th>Applied by</th></tr></thead><tbody>${opex.map((l) => `<tr><td>${esc(l.vendor_name)}</td><td class="num">${l.gl_account}</td>${amt(l.formula_accrual)}${amt(l.final_accrual, "accrual")}<td>${esc(l.applied_by)}</td></tr>`).join("")}</tbody><tfoot><tr><td>Total</td><td></td><td></td><td class="num">${money(snap.summary.totals.vendor_opex)}</td><td></td></tr></tfoot></table></div>`)
      + (register("h-legal", `history_legal_${p}`, [["Vendor", (r) => r.vendor], ["Vendor ID", (r) => r.vendor_id], ["Amount", (r) => r.total], ["JE lines", (r) => r.je_lines.length]], snap.legal.rows),
         register("h-capex", `history_capex_${p}`, [["Deal", (g) => g.deal], ["Project", (g) => g.project_id], ["Vendor", (g) => g.vendor], ["Net earned", (g) => g.net], ["JE", (g) => g.je_amount]], snap.capex.groups), "")
      + panel("h-legal", "Legal", `<div class="filters"><span class="spacer"></span>${exportBtn("h-legal")}</div><div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Amount</th><th>Lines</th></tr></thead><tbody>${snap.legal.rows.map((r) => `<tr><td>${esc(r.vendor)}</td>${amt(r.total)}<td class="num">${r.je_lines.length}</td></tr>`).join("")}</tbody></table></div>`)
      + panel("h-capex", "Capex Projects", `<div class="filters"><span class="spacer"></span>${exportBtn("h-capex")}</div><div class="table-scroll"><table><thead><tr><th>Deal</th><th>Vendor</th><th>Net earned</th><th>JE</th></tr></thead><tbody>${snap.capex.groups.map((g) => `<tr><td>${esc(g.deal)}</td><td>${esc(g.vendor)}</td>${amt(g.net)}${amt(g.je_amount)}</tr>`).join("")}</tbody></table></div>`)
      + panel("h-je", "Journal Entry", `<div class="filters"><span class="spacer"></span>${exportBtn("h-je")}</div><div class="table-scroll"><table><thead><tr><th>Line</th><th>Section</th><th>Account</th><th>Dept</th><th>Location</th><th>Vendor</th><th>Debit</th><th>Credit</th></tr></thead><tbody>${snap.je.lines.map((l) => `<tr class="${l.side === "credit" ? "je-credit" : ""}"><td class="num">${l.line_no}</td><td>${esc(l.section)}</td><td class="num">${l.acct}</td><td>${esc(l.dept)}</td><td>${esc(l.location)}</td><td>${esc(l.vendor_id)}</td>${l.debit ? amt(l.debit) : "<td></td>"}${l.credit ? amt(l.credit) : "<td></td>"}</tr>`).join("")}</tbody></table></div>`);
  }
  return panel("history", "Signed-off months", `<div class="hist-btns">${btns}</div>`) + detail;
}

// ---------- 9. Budget ----------
const CHECK_LABELS = { budget_on_another_account: "Budget on another account", within_phased_budget: "Within phased budget", bills_monthly_no_current_service: "Bills monthly, no current-month service", driven_by_prepaid_or_billed_ahead: "Driven by prepaid / billed ahead", over_full_year_budget: "Over full-year budget" };
function tabBudget(d) {
  const ob = d.over_budget; const b = d.budget;
  const chips = `<div class="chips"><div class="chip"><b>${ob.length}</b>lines over budget YTD</div><div class="chip"><b>${money(sum(ob, "over_by"))}</b>total over</div><div class="chip bad"><b>${ob.filter((o) => o.checks.over_full_year_budget).length}</b>over full-year budget</div></div>`;
  const obRows = ob.map((o) => `<tr><td><span class="vendor-name">${esc(o.vendor_name)}</span><span class="sub">${esc(o.vendor_id)} · ${o.gl_account}</span></td>
    <td class="num amt">${money(o.budget_ytd)}<span class="sub">annual ${money(o.annual_budget)}</span></td>${amt(o.spend_ytd)}
    <td class="num amt neg">${money(o.over_by)}<span class="sub">${pct(o.over_pct)}</span></td>${amt(o.vendor_budget_all_accounts)}<td>${esc(o.last_billed || "")}</td>
    <td class="wrap">${Object.entries(o.checks).filter(([, v]) => v).map(([k]) => `<span class="pill ${k === "over_full_year_budget" ? "bad" : "confirmed"}">${CHECK_LABELS[k]}</span>`).join(" ") || `<span class="pill warn">No explaining check</span>`}</td></tr>`).join("");
  register("over", "over_budget", [["Vendor", (o) => o.vendor_name], ["Account", (o) => o.gl_account], ["Budget YTD", (o) => o.budget_ytd], ["Annual", (o) => o.annual_budget], ["Spend YTD", (o) => o.spend_ytd], ["Over by", (o) => o.over_by], ["Over %", (o) => o.over_pct], ["Vendor budget, all accounts", (o) => o.vendor_budget_all_accounts], ["Last billed", (o) => o.last_billed], ...Object.keys(CHECK_LABELS).map((k) => [CHECK_LABELS[k], (o) => (o.checks[k] ? "Yes" : "")])], ob);
  const over = panel("over", "Over Budget", chips + `<div class="filters"><span class="spacer"></span>${exportBtn("over")}</div><div class="table-scroll"><table><thead><tr><th>Vendor / Account</th><th>Budget YTD</th><th>Spend YTD</th><th>Over by</th><th>Vendor budget, all accounts</th><th>Last billed</th><th>Check</th></tr></thead><tbody>${obRows}</tbody></table></div>`);

  register("bacct", "budget_by_account", [["Account", (a) => a.gl_account], ["Name", (a) => a.name], ["Annual", (a) => a.annual], ["Phased YTD", (a) => a.phased_ytd]], b.by_account);
  const byAcct = panel("bacct", "Budget by GL account", `<div class="filters"><span class="status-text">Budget with no vendor: ${money(b.no_vendor_total)} (shown here, never accrued)</span><span class="spacer"></span>${exportBtn("bacct")}</div><div class="table-scroll"><table><thead><tr><th>Account</th><th>Name</th><th>Annual</th><th>Phased YTD</th></tr></thead><tbody>${b.by_account.map((a) => `<tr><td class="num">${a.gl_account}</td><td>${esc(a.name)}</td>${amt(a.annual)}${amt(a.phased_ytd)}</tr>`).join("")}</tbody><tfoot><tr><td>Total</td><td></td><td class="num">${money(b.total)}</td><td class="num">${money(sum(b.by_account, "phased_ytd"))}</td></tr></tfoot></table></div>`);

  const qv = S.f.budv.q.toLowerCase(); const vs = b.by_vendor.filter((v) => !qv || `${v.vendor_name} ${v.vendor_id}`.toLowerCase().includes(qv));
  register("bvend", "budget_by_vendor", [["Vendor", (v) => v.vendor_name], ["Vendor ID", (v) => v.vendor_id], ["# Accounts", (v) => v.accounts], ["Annual", (v) => v.annual], ["Phased YTD", (v) => v.phased_ytd]], vs);
  const byVendor = panel("bvend", "Budget by vendor", `<div class="filters">${field("Vendor", search("budv.q", S.f.budv.q, "Vendor search"))}<span class="spacer"></span>${exportBtn("bvend")}</div><div class="table-scroll"><table><thead><tr><th>Vendor</th><th># Accounts</th><th>Annual</th><th>Phased YTD</th></tr></thead><tbody>${vs.map((v) => `<tr><td><span class="vendor-name">${esc(v.vendor_name)}</span><span class="sub vendor-id">${esc(v.vendor_id)}</span></td><td class="num">${v.accounts}</td>${amt(v.annual)}${amt(v.phased_ytd)}</tr>`).join("")}</tbody><tfoot><tr><td>Total</td><td></td><td class="num">${money(sum(vs, "annual"))}</td><td class="num">${money(sum(vs, "phased_ytd"))}</td></tr></tfoot></table></div>`);

  const qa = S.f.budva.q.toLowerCase(); const va = b.by_vendor_account.filter((v) => !qa || `${v.vendor_name} ${v.vendor_id} ${v.gl_account}`.toLowerCase().includes(qa));
  register("bva", "budget_by_vendor_account", [["Vendor", (v) => v.vendor_name], ["Vendor ID", (v) => v.vendor_id], ["Account", (v) => v.gl_account], ["Name", (v) => v.name], ["Annual", (v) => v.annual], ["Phased YTD", (v) => v.phased_ytd]], va);
  const byVA = panel("bva", "Budget by vendor × account", `<div class="filters">${field("Vendor", search("budva.q", S.f.budva.q, "Vendor or account"))}<span class="spacer"></span>${exportBtn("bva")}</div><div class="table-scroll"><table><thead><tr><th>Vendor</th><th>Account</th><th>Annual</th><th>Phased YTD</th></tr></thead><tbody>${va.map((v) => `<tr><td><span class="vendor-name">${esc(v.vendor_name)}</span><span class="sub vendor-id">${esc(v.vendor_id)}</span></td><td class="num">${v.gl_account}<span class="sub">${esc(v.name)}</span></td>${amt(v.annual)}${amt(v.phased_ytd)}</tr>`).join("")}</tbody><tfoot><tr><td>Total</td><td></td><td class="num">${money(sum(va, "annual"))}</td><td class="num">${money(sum(va, "phased_ytd"))}</td></tr></tfoot></table></div>`);
  return over + byAcct + byVendor + byVA;
}

// ---------- 10. YTD Transactions ----------
function tabYTD(d) {
  const pvs = d.posting_vs_service;
  register("pvs", "posted_vs_service", [["Month", (r) => r.month], ["GL Total (posted)", (r) => r.gl_total], ["Service Period Total", (r) => r.service_total], ["Variance", (r) => r.variance], ["Lines posted", (r) => r.lines_posted], ["Lines by service", (r) => r.lines_by_service]], pvs);
  const t1 = panel("pvs", "Monthly spend — posted vs. service period", `<div class="filters"><span class="status-text">In-scope GL only. Variance = posted in the month − service in the month.</span><span class="spacer"></span>${exportBtn("pvs")}</div><div class="table-scroll"><table><thead><tr><th>Month</th><th>GL Total (posted)</th><th>Service Period Total</th><th>Variance</th><th>Lines posted</th><th>Lines by service</th></tr></thead><tbody>${pvs.map((r) => `<tr class="${r.current ? "hl" : ""}"><td>${/^\d{4}-\d{2}$/.test(r.month) ? monLabel(r.month) : esc(r.month)}</td>${amt(r.gl_total)}${amt(r.service_total)}${amt(r.variance)}<td class="num">${r.lines_posted}</td><td class="num">${r.lines_by_service}</td></tr>`).join("")}</tbody></table></div>`);

  const f = S.f.gl; const q = f.q.toLowerCase(); const all = d.gl_detail;
  const rows = all.filter((r) => (!f.svc || r.service_month === f.svc) && (!f.post || r.posting_date.startsWith(f.post)) && (!f.acct || String(r.gl_account) === f.acct)
    && (!q || `${r.vendor_name} ${r.vendor_id} ${r.description} ${r.document_id}`.toLowerCase().includes(q)) && (!f.basis || r.basis === f.basis) && (!f.dept || r.department_name === f.dept));
  const svcMonths = uniq(all.map((r) => r.service_month)).sort().reverse(); const postMonths = uniq(all.map((r) => r.posting_date.slice(0, 7))).sort().reverse();
  const accts = uniq(all.map((r) => r.gl_account)).sort(); const depts = uniq(all.map((r) => r.department_name)).sort();
  const seg = `<div class="seg" role="group" aria-label="Service date basis">${[["", "All"], ["Confirmed", "Confirmed"], ["Estimated", "Estimated"]].map(([v, l]) => `<button type="button" class="${f.basis === v ? "on" : ""}" data-action="basis" data-v="${v}">${l}</button>`).join("")}</div>`;
  const filters = `<div class="filters">${field("Service Month", sel("gl.svc", f.svc, opt("", "All", f.svc) + svcMonths.map((m) => opt(m, m, f.svc)).join("")))}
    ${field("Posting Month", sel("gl.post", f.post, opt("", "All", f.post) + postMonths.map((m) => opt(m, m, f.post)).join("")))}
    ${field("Account", sel("gl.acct", f.acct, opt("", "All", f.acct) + accts.map((a) => opt(a, a, f.acct)).join("")))}
    ${field("Vendor", search("gl.q", f.q, "Vendor search"))}${field("Service Date", seg)}
    ${field("Dept", sel("gl.dept", f.dept, opt("", "All", f.dept) + depts.map((x) => opt(x, x, f.dept)).join("")))}<span class="spacer"></span>${exportBtn("gl")}</div>`;
  const LIMIT = 1200;
  const body = rows.slice(0, LIMIT).map((r) => `<tr><td>${esc(r.posting_date)}</td><td class="num">${r.gl_account}<span class="sub">${esc(r.gl_account_name)}</span></td>
    <td><span class="vendor-name">${esc(r.vendor_name)}</span><span class="sub vendor-id">${esc(r.vendor_id)} · ${esc(r.document_id)}</span></td><td>${esc(r.department_name)}</td><td>${esc(r.location_name)}</td><td>${esc(r.journal)}</td>
    <td>${r.service_from ? `${esc(r.service_from)} – ${esc(r.service_to)}` : esc(r.service_month)}<span class="sub">${esc(r.service_month)} · ${esc(r.service_source)}</span></td>
    <td><span class="pill ${r.basis === "Confirmed" ? "confirmed" : "estimated"}">${esc(r.basis)}</span></td>${amt(r.amount)}</tr>`).join("");
  register("gl", "gl_detail", [["Posting Date", (r) => r.posting_date], ["Account", (r) => r.gl_account], ["Vendor", (r) => r.vendor_name], ["Vendor ID", (r) => r.vendor_id], ["Dept", (r) => r.department_name], ["Location", (r) => r.location_name], ["Journal", (r) => r.journal], ["Service From", (r) => r.service_from], ["Service To", (r) => r.service_to], ["Service Month", (r) => r.service_month], ["Source", (r) => r.service_source], ["Basis", (r) => r.basis], ["Amount", (r) => r.amount], ["Memo", (r) => r.description], ["Document", (r) => r.document_id]], rows);
  const t2 = panel("gl", "GL Detail", filters + `<div class="table-scroll"><table><thead><tr><th>Posting Date</th><th>Account</th><th>Vendor</th><th>Dept</th><th>Location</th><th>Journal</th><th>Service Period</th><th>Basis</th><th>Amount</th></tr></thead><tbody>${body}</tbody>
    <tfoot><tr><td>Total</td><td colspan="7"></td><td class="num">${money(sum(rows, "amount"))}</td></tr></tfoot></table></div><div class="count-note">Showing ${Math.min(rows.length, LIMIT).toLocaleString()} of ${rows.length.toLocaleString()} matching rows (${all.length.toLocaleString()} in scope). Export includes all matching rows.</div>`);
  return t1 + t2;
}

// ---------- modals ----------
function modal(title, body, foot = "") {
  document.getElementById("modal-root").innerHTML = `<div class="ov-back" data-action="modal-back"><div class="ov-card" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <div class="ov-head"><h3>${esc(title)}</h3><button class="btn" data-action="modal-close" type="button" aria-label="Close">✕</button></div>
    <div class="ov-body">${body}<div class="err" id="m-err"></div></div>${foot ? `<div class="ov-foot">${foot}</div>` : ""}</div></div>`;
  const first = document.querySelector("#modal-root input, #modal-root textarea"); if (first) first.focus();
}
const closeModal = () => { document.getElementById("modal-root").innerHTML = ""; };
const mErr = (t) => { const e = document.getElementById("m-err"); if (e) e.textContent = t; };
const mval = (id) => (document.getElementById(id) || {}).value ?? "";

async function openOverride(key) {
  const l = S.data.vendor_opex.lines.find((x) => x.key === key); if (!l) return;
  let log = [];
  try { log = await api("GET", `${P()}/override-log?key=${encodeURIComponent(key)}`); } catch (_) { /* no log yet */ }
  const o = l.override;
  const body = `<p><b>${esc(l.vendor_name)}</b> · ${l.gl_account} ${esc(l.gl_account_name)}<br>Calculated accrual <span class="num">${money(l.formula_accrual)}</span>${l.standing ? ` · standing rule ${money(l.standing.amount)}` : ""} · current final <span class="num">${money(l.final_accrual)}</span></p>
    <div class="form-grid"><div class="field"><label for="ov-amt">Override amount</label><input type="text" id="ov-amt" value="${o ? esc(o.amount) : ""}" placeholder="0.00"></div>
    <div class="field full"><label for="ov-exp">Explanation (5+ characters, required to save or remove)</label><textarea id="ov-exp">${o ? esc(o.explanation) : ""}</textarea></div></div>
    ${log.length ? `<h4>Override log</h4><div class="table-scroll" style="max-height:200px"><table><thead><tr><th>When</th><th>Action</th><th>Amount</th><th>Explanation</th><th>Who</th></tr></thead><tbody>${log.map((e) => `<tr><td>${esc(when(e.at))}</td><td>${esc(e.action)}</td>${amt(e.amount)}<td class="wrap">${esc(e.explanation)}</td><td>${esc(e.user)}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  modal("Override accrual", body, `${o ? `<button class="btn danger" data-action="ovr-remove" data-key="${esc(key)}" type="button">Remove override</button>` : ""}<span class="spacer"></span><button class="btn" data-action="modal-close" type="button">Cancel</button><button class="btn primary" data-action="ovr-save" data-key="${esc(key)}" type="button">Save override</button>`);
}
function openManual(prefill = {}) {
  const fields = [["vendor", "Vendor"], ["vendor_id", "Vendor ID"], ["gl_account", "Account (5 digits)"], ["amount", "Amount"], ["dept", "Dept ID"], ["location", "Location ID"], ["item", "Item ID"]];
  const body = `<p class="status-text">For a vendor that is not on the roster, current period (${esc(S.data.period_label)}) only.</p><div class="form-grid">${fields.map(([k, l]) => `<div class="field"><label for="ma-${k}">${l}</label><input type="text" id="ma-${k}" value="${esc(prefill[k] || "")}"></div>`).join("")}
    <div class="field full"><label for="ma-explanation">Explanation (5+ characters)</label><textarea id="ma-explanation"></textarea></div></div>`;
  modal("Add manual accrual", body, `<button class="btn" data-action="modal-close" type="button">Cancel</button><button class="btn primary" data-action="manual-save" type="button">Add accrual</button>`);
}
function splitLineRow(s, i) {
  return `<tr data-split="${i}"><td><input type="text" class="amt-in" id="sp-amount-${i}" value="${esc(s.amount ?? "")}" aria-label="Amount"></td><td><input type="text" id="sp-gl-${i}" value="${esc(s.gl ?? "")}" aria-label="GL"></td><td><input type="text" id="sp-item-${i}" value="${esc(s.item ?? "")}" aria-label="Item"></td><td><input type="text" id="sp-note-${i}" value="${esc(s.note ?? "")}" aria-label="Note"></td><td><button class="btn small danger" data-action="split-del" data-i="${i}" type="button">✕</button></td></tr>`;
}
let SPLIT = { vid: null, lines: [] };
function readSplit() { SPLIT.lines = SPLIT.lines.map((_, i) => ({ amount: mval(`sp-amount-${i}`), gl: mval(`sp-gl-${i}`), item: mval(`sp-item-${i}`), note: mval(`sp-note-${i}`) })); }
function openSplit(vid) {
  const r = S.data.legal.rows.find((x) => x.vendor_id === vid);
  SPLIT = { vid, lines: r.splits ? r.splits.map((s) => ({ ...s })) : [{ amount: r.amount, gl: r.gl, item: r.item, note: r.note }, { amount: "", gl: "", item: r.item, note: "" }] };
  drawSplit(r);
}
function drawSplit(r) {
  r = r || S.data.legal.rows.find((x) => x.vendor_id === SPLIT.vid);
  const body = `<p><b>${esc(r.vendor)}</b> — split across two or more GL lines. The firm total is the sum of the lines; each line is its own JE debit with the firm's customer, project, dept and location.</p>
    <table><thead><tr><th>Amount</th><th>GL (5 digits)</th><th>Item</th><th>Note</th><th></th></tr></thead><tbody>${SPLIT.lines.map(splitLineRow).join("")}</tbody></table>
    <p><button class="btn small" data-action="split-add" type="button">+ Add line</button></p>`;
  modal("Split legal accrual", body, `${r.splits ? `<button class="btn danger" data-action="split-remove" type="button">Remove split</button>` : ""}<span class="spacer"></span><button class="btn" data-action="modal-close" type="button">Cancel</button><button class="btn primary" data-action="split-save" type="button">Save split</button>`);
}

// ---------- events ----------
function setFilter(path, value) { const [a, b] = path.split("."); S.f[a][b] = value; render(); }

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.filter && t.tagName === "INPUT") setFilter(t.dataset.filter, t.value);
  if (t.dataset.legal) {
    const vid = t.dataset.legal; (S.legalDirty[vid] = S.legalDirty[vid] || {})[t.dataset.field] = t.value;
    const row = t.closest("tr"); if (row) row.classList.add("row-dirty");
  }
});
document.addEventListener("change", async (e) => {
  const t = e.target;
  if (t.id === "period-select") { S.period = t.value; S.signConfirm = false; S.legalDirty = {}; await load(); return; }
  if (t.dataset.filter && t.tagName === "SELECT") setFilter(t.dataset.filter, t.value);
  if (t.dataset.review) await act("POST", `${P()}/mom/review`, { key: t.dataset.review, reviewed: t.checked });
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-action]"); if (!el) return;
  const a = el.dataset.action;
  if (a === "modal-back" && e.target !== el) return;
  switch (a) {
    case "tab": S.tab = el.dataset.tab; render(); window.scrollTo(0, 0); break;
    case "toggle": { const id = el.dataset.panel; S.collapsed.has(id) ? S.collapsed.delete(id) : S.collapsed.add(id); render(); break; }
    case "export": downloadCSV(el.dataset.id); break;
    case "sort": { const k = el.dataset.key; S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : 1 }; render(); break; }
    case "basis": S.f.gl.basis = el.dataset.v; render(); break;
    case "modal-back": case "modal-close": closeModal(); break;
    case "signoff-start": S.signConfirm = true; render(); break;
    case "signoff-cancel": S.signConfirm = false; render(); break;
    case "signoff-confirm": S.signConfirm = false;
      if (await act("POST", `${P()}/signoff`, null, `${S.data.period_label} signed off and locked`)) { await loadMeta(); render(); }
      break;
    case "component": await act("POST", `${P()}/component`, { component: el.dataset.c, complete: el.dataset.v === "1" }); break;
    case "ovr-open": openOverride(el.dataset.key); break;
    case "ovr-save":
      try { await api("POST", `${P()}/override`, { key: el.dataset.key, amount: mval("ov-amt"), explanation: mval("ov-exp") }); closeModal(); await load(); toast("Override saved"); }
      catch (err) { mErr(err.message); }
      break;
    case "ovr-remove":
      try { await api("POST", `${P()}/override/remove`, { key: el.dataset.key, explanation: mval("ov-exp") }); closeModal(); await load(); toast("Override removed"); }
      catch (err) { mErr(err.message); }
      break;
    case "manual-open": openManual({ vendor: el.dataset.vendor, vendor_id: el.dataset.vid, gl_account: el.dataset.acct }); break;
    case "manual-save": {
      const entry = Object.fromEntries(["vendor", "vendor_id", "gl_account", "amount", "dept", "location", "item", "explanation"].map((k) => [k, mval(`ma-${k}`)]));
      try { await api("POST", `${P()}/manual`, entry); closeModal(); await load(); toast("Manual accrual added"); } catch (err) { mErr(err.message); }
      break;
    }
    case "manual-delete": await act("DELETE", `${P()}/manual/${el.dataset.id}`, null, "Manual add deleted"); break;
    case "legal-save": {
      const vid = el.dataset.vid; const fields = S.legalDirty[vid] || {};
      if (await act("POST", `${P()}/legal/${encodeURIComponent(vid)}`, { fields, splits: (S.data.legal.rows.find((r) => r.vendor_id === vid) || {}).splits }, "Legal row saved")) { delete S.legalDirty[vid]; render(); }
      break;
    }
    case "legal-split": openSplit(el.dataset.vid); break;
    case "split-add": readSplit(); SPLIT.lines.push({ amount: "", gl: "", item: "", note: "" }); drawSplit(); break;
    case "split-del": readSplit(); SPLIT.lines.splice(+el.dataset.i, 1); drawSplit(); break;
    case "split-save": readSplit();
      try { await api("POST", `${P()}/legal/${encodeURIComponent(SPLIT.vid)}`, { fields: S.legalDirty[SPLIT.vid] || {}, splits: SPLIT.lines }); delete S.legalDirty[SPLIT.vid]; closeModal(); await load(); toast("Split saved"); }
      catch (err) { mErr(err.message); }
      break;
    case "split-remove": {
      const r = S.data.legal.rows.find((x) => x.vendor_id === SPLIT.vid);
      try { await api("POST", `${P()}/legal/${encodeURIComponent(SPLIT.vid)}`, { fields: { amount: String(r.total), gl: String(r.splits[0].gl) }, splits: null }); closeModal(); await load(); toast("Split removed"); }
      catch (err) { mErr(err.message); }
      break;
    }
    case "legal-add-toggle": S.ui.legalAdd = !S.ui.legalAdd; render(); break;
    case "legal-add-save": {
      const row = Object.fromEntries(["vendor", "vendor_id", "amount", "gl", "item", "customer", "project", "dept", "location", "note"].map((k) => [k, mval(`la-${k}`)]));
      if (await act("POST", `${P()}/legal-add`, row, "Legal vendor added")) { S.ui.legalAdd = false; render(); }
      break;
    }
    case "standing-confirm": await act("POST", `${P()}/standing/confirm`, { key: el.dataset.key }, "Standing rule confirmed"); break;
    case "att-add-toggle": S.ui.attAdd = !S.ui.attAdd; render(); break;
    case "att-add-save": {
      const item = Object.fromEntries(["category", "vendor", "vendor_id", "account", "amount", "summary", "detail", "proposed", "assignee"].map((k) => [k, mval(`aa-${k}`)]));
      if (await act("POST", `${P()}/attention`, item, "Item added")) { S.ui.attAdd = false; render(); }
      break;
    }
    case "att-save": {
      const id = el.dataset.id;
      await act("PATCH", `/api/period/${el.dataset.period}/attention/${id}`, { assignee: mval(`att-as-${id}`), status: mval(`att-st-${id}`), resolution: mval(`att-res-${id}`) }, "Item saved");
      break;
    }
    case "history-open":
      try { S.history = await api("GET", `/api/history/${el.dataset.p}`); S.historyPeriod = el.dataset.p; render(); } catch (err) { toast(err.message, true); }
      break;
    default: break;
  }
});

// ---------- 11. Settings ----------
async function loadSettings() { S.settings = await api("GET", "/api/settings"); }
async function refreshAll(msg) {
  await loadMeta(); await loadSettings();
  if (!S.meta.periods.includes(S.period)) S.period = S.meta.current_period;
  document.getElementById("period-select").innerHTML = S.meta.periods.map((p) => opt(p, monLabel(p), S.period)).join("");
  S.history = null; S.historyPeriod = null; S.legalDirty = {};
  await load(); if (msg) toast(msg);
}
function tabSettings() {
  const s = S.settings;
  if (!s) return `<div class="loading">Loading settings…</div>`;
  const mine = s.dataset === "user";
  const seg = `<div class="seg" role="group" aria-label="Data set">${s.datasets.map((x) => `<button type="button" class="${s.dataset === x.id ? "on" : ""}" data-action="dataset" data-v="${x.id}">${esc(x.label)}</button>`).join("")}</div>`;
  const dsNote = mine
    ? `You are working on <b>your own data</b>. Files are saved in <code>${esc(s.user_dir)}</code>, which is kept out of the git repo. Edits and sign-offs for this data set are stored separately from the sample.`
    : `You are viewing the <b>sample data</b> (invented, read-only). Switch to <b>My data</b> to upload your own chart of accounts, budget and the rest. Templates and examples can be downloaded either way.`;
  const dataset = panel("set-ds", "Data set", `<div class="filters">${field("Use", seg)}<span class="status-text" style="max-width:760px">${dsNote}</span></div>`);

  const g = s.general;
  const general = mine ? panel("set-gen", "Company and open month", `<div class="filters">
      ${field("Company name", `<input type="text" id="st-company" value="${esc(g.company)}">`)}
      ${field("Open month (YYYY-MM)", `<input type="text" id="st-period" value="${esc(g.current_period)}" size="9">`)}
      <button class="export" data-action="settings-general" type="button">Save</button>
      <span class="status-text">The open month is the latest period; manual adds are allowed only there. The fiscal year runs January–December.</span></div>`) : "";

  const rows = s.files.map((f, i) => {
    const msg = S.uploadMsg[f.name];
    return `<tr class="${f.problem ? "hl" : ""}"><td class="num">${i + 1}</td>
      <td><span class="vendor-name">${esc(f.label)}</span><span class="sub vendor-id">${esc(f.name)}</span></td>
      <td class="wrap">${esc(f.description)}<details><summary>Required columns (${f.columns.length})</summary><span class="sub">${esc(f.columns.join(", "))}</span></details>
        ${f.problem ? `<span class="sub neg">${esc(f.problem)}</span>` : ""}${msg ? `<span class="sub ${msg.bad ? "neg" : "pos"}">${esc(msg.text)}</span>` : ""}</td>
      <td class="num">${f.rows.toLocaleString()}</td><td>${esc(f.updated || "")}</td>
      <td><a class="btn small" href="/api/settings/template/${f.name}">Template</a> <a class="btn small" href="/api/settings/example/${f.name}">Example</a></td>
      <td>${mine ? `<label class="btn small primary" style="display:inline-block">Upload CSV<input type="file" accept=".csv,text/csv" data-upload="${f.name}" hidden></label>` : `<span class="status-text">—</span>`}</td>
      <td>${f.rows ? `<a class="btn small" href="/api/settings/file/${f.name}">Download</a>` : ""}</td></tr>`;
  }).join("");
  const lvl = { error: "bad", warning: "warn", info: "muted" };
  const checkRows = (s.checks || []).map((c) => `<tr><td><span class="pill ${lvl[c.level]}">${esc(c.level)}</span></td><td>${esc(c.files)}</td>
      <td class="wrap"><b>${esc(c.message)}</b>${c.hint ? `<span class="sub">${esc(c.hint)}</span>` : ""}</td><td class="num">${c.count || ""}</td>
      <td class="wrap">${esc(c.examples.join(", "))}${c.count > c.examples.length ? " …" : ""}</td></tr>`).join("");
  const checks = panel("set-checks", "Data checks across files", `<div class="note">These compare your files with each other: things a single upload cannot catch. Errors will give wrong numbers; warnings are probably mistakes. Last month's JE and MoM figures currently come from: <b>${esc(s.prior_source)}</b>.</div>
    ${checkRows ? `<div class="table-scroll"><table><thead><tr><th>Level</th><th>File</th><th>Check</th><th>Count</th><th>Examples</th></tr></thead><tbody>${checkRows}</tbody></table></div>` : `<div class="count-note">✓ No problems found across the files.</div>`}`);
  const files = checks + panel("set-files", mine ? "Upload your data" : "Input files", `<div class="note">Upload in this order, chart of accounts first. Each file is checked before it is saved: missing columns or a bad date or number in any row are rejected with the row number, and nothing changes. Headers like "Vendor ID" are fine (case and spaces don't matter). Dates: YYYY-MM-DD or MM/DD/YYYY. Each upload replaces that whole file.</div>
    <div class="table-scroll"><table><thead><tr><th>#</th><th>File</th><th>What it is</th><th>Rows</th><th>Updated</th><th>Get started</th><th>Upload</th><th>Current</th></tr></thead><tbody>${rows}</tbody></table></div>`);

  const m = s.inputs_meta;
  const metaPanel = mine ? panel("set-meta", "One-number inputs", `<div class="filters">
      ${field("Capex GL not yet allocated", `<input type="text" id="st-unalloc" value="${esc(m.unallocated_gl_total)}" size="12">`)}
      ${field("Capex lines needing attention", `<input type="text" id="st-nacount" value="${esc(m.needs_attention_count)}" size="5">`)}
      ${field("Capex attention amount", `<input type="text" id="st-natotal" value="${esc(m.needs_attention_total)}" size="12">`)}
      ${field("Last month (YYYY-MM)", `<input type="text" id="st-prior" value="${esc(m.prior_period || "")}" size="9">`)}
      ${field("Last month's JE reversed on the 1st", `<input type="text" id="st-rev" value="${esc(m.reversed_total)}" size="12">`)}
      <button class="export" data-action="settings-meta" type="button">Save</button></div>`) : "";

  const rulesPanel = mine ? panel("set-rules", "Advanced rules (rules.yaml)", `<div class="filters"><span class="status-text" style="max-width:700px">Account ranges, the accrued-expenses account, standing rules, rollups, budget-line overrides and department splits live in <code>rules.yaml</code>. Your copy started from the sample rules with every vendor-specific exception removed. Download it, edit it in any text editor and upload it back; it is checked by running the workbook before it is saved.</span><span class="spacer"></span>
      <a class="export secondary" href="/api/settings/file/rules.yaml">Download rules.yaml</a>
      <label class="export" style="display:inline-block">Upload rules.yaml<input type="file" accept=".yaml,.yml" data-upload-rules="1" hidden></label></div>`) : "";

  const reset = mine ? panel("set-reset", "Start over", `<div class="filters"><span class="status-text">Deletes your uploaded files, settings, edits and sign-offs for My data. The sample data is not affected.</span><span class="spacer"></span>
      ${field("Type RESET to confirm", `<input type="text" id="st-reset" size="8">`)}<button class="btn danger" data-action="settings-reset" type="button">Delete my data</button></div>`) : "";
  return dataset + general + files + metaPanel + rulesPanel + reset;
}
async function uploadFile(url, file) {
  const fd = new FormData(); fd.append("file", file);
  const r = await fetch(url, { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Upload failed (${r.status})`);
  return j;
}
document.addEventListener("change", async (e) => {
  const t = e.target;
  if (t.dataset.upload && t.files.length) {
    const name = t.dataset.upload;
    try { const j = await uploadFile(`/api/settings/upload/${name}`, t.files[0]); S.uploadMsg[name] = { text: `Saved: ${j.rows.toLocaleString()} rows loaded.` }; await refreshAll(`${name}: ${j.rows} rows loaded`); }
    catch (err) { S.uploadMsg[name] = { text: err.message, bad: true }; render(); toast(`${name} was not saved`, true); }
  }
  if (t.dataset.uploadRules && t.files.length) {
    try { await uploadFile("/api/settings/rules", t.files[0]); await refreshAll("rules.yaml saved"); }
    catch (err) { toast(err.message, true); }
  }
});
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-action]"); if (!el) return;
  const a = el.dataset.action;
  try {
    if (a === "dataset" && el.dataset.v !== S.settings.dataset) {
      await api("POST", "/api/settings/dataset", { dataset: el.dataset.v }); S.uploadMsg = {};
      await refreshAll(`Switched to ${el.textContent}`);
    } else if (a === "settings-general") {
      await api("POST", "/api/settings/general", { company: mval("st-company"), current_period: mval("st-period") }); await refreshAll("Settings saved");
    } else if (a === "settings-meta") {
      await api("POST", "/api/settings/inputs-meta", { unallocated_gl_total: mval("st-unalloc"), needs_attention_count: mval("st-nacount"), needs_attention_total: mval("st-natotal"), prior_period: mval("st-prior"), reversed_total: mval("st-rev") });
      await refreshAll("Saved");
    } else if (a === "settings-reset") {
      await api("POST", "/api/settings/reset", { confirm: mval("st-reset") }); S.uploadMsg = {}; await refreshAll("My data was reset");
    } else if (a === "rollover") {
      const j = await api("POST", `${P()}/rollover`, {});
      S.period = j.next; await refreshAll(`${monLabel(j.next)} is open. Upload this month's GL detail on the Settings tab.`);
    } else if (a === "tab" && el.dataset.tab === "settings") {
      await loadSettings(); render();
    }
  } catch (err) { toast(err.message, true); }
});

// ---------- static text ----------
const OVERVIEW = `
<h4>What this workbook does</h4>
<p>At month-end it estimates expenses Sample Co. has incurred but not yet been billed for, and builds the journal entry that books them (dated the last day of the month, auto-reversing on the 1st). The total accrual is Vendor OpEx + Legal + Capex Projects.</p>
<h4>Vendor OpEx</h4>
<ul><li>Only AP bills and unbilled receipts on in-scope accounts count; nothing posted after month-end.</li>
<li>Each bill is placed in a service month: the bill's service period, else a date in the memo, else its posting month (Estimated).</li>
<li>Budget YTD = annual budget × months elapsed ÷ 12. Spend YTD = service months Jan–cutoff + the current-year share of a prepaid + bills for service after the cutoff.</li>
<li>Accrual = MAX(Budget YTD + prior-year liability remaining − Spend YTD, $0).</li>
<li>Standing rules (e.g. "billed in full", "rate × unbilled months") replace the formula from the month after their baseline; a vendor billed through month-end accrues $0 (except any unpaid prior-year liability). Changes that look risky are flagged for a human to confirm.</li>
<li>A reviewer can override any line (with an explanation) or add a vendor that is not on the roster.</li></ul>
<h4>Legal</h4><p>Law-firm estimates entered per firm; one firm can be split across GL lines.</p>
<h4>Capex Projects</h4><p>Cost × % complete − invoiced to date, netted by project + vendor and never below $0. Not final while capex GL is unallocated.</p>
<h4>Review and sign-off</h4><p>The JE must balance and tie to each tab. Sign-off needs no open needs-attention items, every large swing (≥ $10K and ≥ 25%) reviewed, all three components complete, every flagged standing rule confirmed and a JE that passes all four checks. Signing off saves a read-only snapshot and locks the month.</p>`;
const DEFS = [
  ["Summary", "Sign-off checklist, the A + B + C = Total bridge, component status and GL scope."],
  ["Vendor OpEx", "One row per roster vendor + account: budget, spend, liability, formula, standing rule, override and final accrual, with spend by service month."],
  ["Legal", "Editable law-firm accruals, splits and added firms."],
  ["Capex Projects", "Read-only project tracker accrual netted by project + vendor."],
  ["Needs Attention", "Standing rules carried forward (confirm flagged ones) and the open-items log."],
  ["MoM Review", "Prior month vs current month per vendor + account with a driver and explanation; review large swings."],
  ["Journal Entry", "Every JE line with dimensions, the four tie-out checks and the downloads."],
  ["History", "Signed-off months with their saved JE and backup."],
  ["Budget", "Over-budget lines with checks, and budget by account, vendor and vendor × account."],
  ["YTD Transactions", "Posted vs service-month totals and the in-scope GL detail with Confirmed / Estimated service dates."],
  ["Settings", "Switch between the sample data and your own data, upload your CSV files, and edit company, open month and rules."],
];
document.getElementById("btn-overview").addEventListener("click", () => modal("Overview", `<div class="prose" style="padding:0">${OVERVIEW}</div>`));
document.getElementById("btn-defs").addEventListener("click", () => modal("Tab Definitions", `<table><tbody>${DEFS.map(([t, d]) => `<tr><td><b>${t}</b></td><td class="wrap">${d}</td></tr>`).join("")}</tbody></table>`));

// ---------- boot ----------
(async function boot() {
  try { await loadMeta(); } catch (e) { document.getElementById("main").innerHTML = `<div class="loading">${esc(e.message)}</div>`; return; }
  S.period = S.meta.current_period;
  document.getElementById("period-select").innerHTML = S.meta.periods.map((p) => opt(p, monLabel(p), S.period)).join("");
  await load();
})();
