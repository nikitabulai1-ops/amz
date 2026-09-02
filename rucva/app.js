"use strict";

/* ============================================================
   Storage
   ============================================================ */

const STORE_KEY = "rucva-data-v1";

function defaultDB() {
  return {
    settings: {
      monthlyGoal: 10000,
      minMarginPct: 15,
      googleClientId: "",
      sheetId: "",
      driveFolderId: "",
      ttsEnabled: true,
    },
    products: [],       // COGS tracker rows
    tasks: [],
    metrics: [],         // {date, revenue, profit, units, fbaRevenue, fbmRevenue}
    ungating: [],
    chat: [],
    analyzerLog: [],
    sourcingSession: { count: 0, worthBuying: 0 },
  };
}

function loadDB() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return defaultDB();
    const parsed = JSON.parse(raw);
    return Object.assign(defaultDB(), parsed, {
      settings: Object.assign(defaultDB().settings, parsed.settings || {}),
    });
  } catch (e) {
    return defaultDB();
  }
}

let DB = loadDB();
function saveDB() { localStorage.setItem(STORE_KEY, JSON.stringify(DB)); }

/* ============================================================
   Small helpers
   ============================================================ */

function uid() { return Math.random().toString(36).slice(2, 10); }
function todayISO() { return new Date().toISOString().slice(0, 10); }
function fmtMoney(n) {
  if (n == null || isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(n) { return n == null || isNaN(n) ? "—" : n.toFixed(1) + "%"; }
function daysBetween(a, b) { return Math.floor((b - a) / 86400000); }

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  attrs = attrs || {};
  for (const k in attrs) {
    if (k === "class") node.className = attrs[k];
    else if (k === "html") node.innerHTML = attrs[k];
    else if (k.startsWith("on") && typeof attrs[k] === "function") node.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) node.setAttribute(k, attrs[k]);
  }
  (children || []).forEach((c) => { if (c != null) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
  return node;
}

function verdictBadgeClass(v) { return v === "BUY" ? "buy" : v === "SKIP" ? "skip" : "marginal"; }

/* ============================================================
   Calculators — same verified logic used across this project
   ============================================================ */

const FEE = {
  FUEL_SURCHARGE_PCT: 0.035,
  MIN_REFERRAL_FEE: 0.30,
  REFERRAL_FEE_TABLE: {
    default: 0.15, electronics: 0.08, computers: 0.08, major_appliances: 0.08, video_game_consoles: 0.08,
    amazon_device_accessories: 0.45, automotive_powersports: 0.12, industrial_scientific: 0.12,
    grocery_gourmet: [[15.00, 0.08], [null, 0.15]], beauty_personal_care: [[10.00, 0.08], [null, 0.15]],
    furniture: [[200.00, 0.15], [null, 0.10]], jewelry: [[250.00, 0.20], [null, 0.05]],
    watches: [[1500.00, 0.16], [null, 0.03]], clothing_accessories: [[15.00, 0.05], [20.00, 0.10], [null, 0.17]],
    baby_products: [[10.00, 0.08], [null, 0.15]],
  },
  SMALL_STANDARD_FEES: {
    2: { under_10: 2.88, mid_10_50: 3.06, over_50: 3.57 }, 4: { under_10: 3.00, mid_10_50: 3.19, over_50: 3.70 },
    6: { under_10: 3.13, mid_10_50: 3.33, over_50: 3.84 }, 10: { under_10: 3.33, mid_10_50: 3.53, over_50: 4.04 },
    16: { under_10: 3.60, mid_10_50: 3.81, over_50: 4.32 },
  },
  LARGE_STANDARD_FEES: {
    1: { mid_10_50: 4.20, over_50: 4.51 }, 2: { mid_10_50: 4.75, over_50: 5.06 },
    3: { mid_10_50: 5.42, over_50: 5.73 }, 20: { mid_10_50: 8.42, over_50: 8.73 },
  },
};

function round2(n, d) { d = d === undefined ? 2 : d; const f = Math.pow(10, d); return Math.round((n + Number.EPSILON) * f) / f; }

function referralFeeFor(category, price) {
  const rule = FEE.REFERRAL_FEE_TABLE[category] ?? FEE.REFERRAL_FEE_TABLE.default;
  let rate;
  if (typeof rule === "number") { rate = rule; }
  else {
    rate = rule[rule.length - 1][1];
    for (const [ceiling, pct] of rule) { if (ceiling !== null && price <= ceiling) { rate = pct; break; } }
  }
  return [Math.max(round2(price * rate), FEE.MIN_REFERRAL_FEE), rate];
}
function priceBracket(price) { return price < 10 ? "under_10" : price <= 50 ? "mid_10_50" : "over_50"; }
function tableLookup(table, weight) {
  const keys = Object.keys(table).map(Number).sort((a, b) => a - b);
  for (const k of keys) if (weight <= k) return table[k];
  return table[keys[keys.length - 1]];
}
function estFulfillmentFee(sellPrice, weightOz) {
  const base = tableLookup(FEE.SMALL_STANDARD_FEES, weightOz || 8)[priceBracket(sellPrice)];
  return round2(base * (1 + FEE.FUEL_SURCHARGE_PCT));
}

function calcFbaEconomics(input) {
  if (!(input.sellPrice > 0)) throw new Error("Sale price must be greater than 0");
  if (!(input.cost >= 0)) throw new Error("Cost must be 0 or greater");
  const category = input.category || "default";
  const landedCost = round2(input.cost + (input.otherCost || 0));
  const [referralFee, referralPct] = referralFeeFor(category, input.sellPrice);
  const fulfillmentFee = estFulfillmentFee(input.sellPrice, input.weightOz);
  const totalFees = round2(referralFee + fulfillmentFee);
  const netProfit = round2(input.sellPrice - landedCost - totalFees);
  const marginPct = round2((netProfit / input.sellPrice) * 100);
  const roiPct = landedCost ? round2((netProfit / landedCost) * 100) : 0;
  const breakeven = referralPct < 1 ? round2((landedCost + fulfillmentFee) / (1 - referralPct)) : null;
  let verdict = "BUY";
  if (marginPct < 10 || roiPct < 20) verdict = "SKIP";
  else if (marginPct < 15 || roiPct < 30) verdict = "MARGINAL";
  return { landedCost, referralFee, referralPct, fulfillmentFee, totalFees, netProfit, marginPct, roiPct, breakeven, verdict };
}

function calcFbmEconomics(input) {
  if (!(input.sellPrice > 0)) throw new Error("Sale price must be greater than 0");
  if (!(input.cost >= 0)) throw new Error("Cost must be 0 or greater");
  const category = input.category || "default";
  const landedCost = round2(input.cost + (input.otherCost || 0));
  const [referralFee, referralPct] = referralFeeFor(category, input.sellPrice);
  const shipCost = input.shippingCost || 0;
  const totalFees = round2(referralFee + shipCost);
  const netProfit = round2(input.sellPrice - landedCost - totalFees);
  const marginPct = round2((netProfit / input.sellPrice) * 100);
  const roiPct = landedCost ? round2((netProfit / landedCost) * 100) : 0;
  const breakeven = referralPct < 1 ? round2((landedCost + shipCost) / (1 - referralPct)) : null;
  let verdict = "BUY";
  if (marginPct < 10 || roiPct < 20) verdict = "SKIP";
  else if (marginPct < 15 || roiPct < 30) verdict = "MARGINAL";
  return { landedCost, referralFee, referralPct, shipCost, totalFees, netProfit, marginPct, roiPct, breakeven, verdict };
}

function riskLevel({ fbaSellerCount, amazonOnListing, bsr }) {
  let score = 0;
  if (amazonOnListing) score += 2;
  if (fbaSellerCount >= 10) score += 2; else if (fbaSellerCount >= 4) score += 1;
  if (bsr && bsr > 200000) score += 1;
  if (score >= 3) return "High";
  if (score >= 1) return "Medium";
  return "Low";
}

/* ============================================================
   CSV export
   ============================================================ */

function toCsv(rows, columns) {
  const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const header = columns.map((c) => esc(c.label)).join(",");
  const body = rows.map((r) => columns.map((c) => esc(typeof c.get === "function" ? c.get(r) : r[c.key])).join(",")).join("\n");
  return header + "\n" + body;
}
function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ============================================================
   Google Sheets / Drive (client-side OAuth via Google Identity Services)
   No backend involved — needs the user's own OAuth Client ID (public,
   safe to store client-side) from Google Cloud Console. See README.
   ============================================================ */

const Google = {
  tokenClient: null,
  accessToken: null,
  scopes: "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file",

  ready() { return !!(window.google && window.google.accounts && window.google.accounts.oauth2); },

  ensureClient() {
    if (!this.ready()) throw new Error("Google Identity Services hasn't loaded yet — check your internet connection and reload.");
    if (!DB.settings.googleClientId) throw new Error("No Google Client ID configured. Add one in Settings first.");
    if (!this.tokenClient) {
      this.tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: DB.settings.googleClientId,
        scope: this.scopes,
        callback: () => {}, // overridden per-call below
      });
    }
    return this.tokenClient;
  },

  connect() {
    return new Promise((resolve, reject) => {
      try {
        const client = this.ensureClient();
        client.callback = (resp) => {
          if (resp.error) reject(new Error(resp.error));
          else { this.accessToken = resp.access_token; resolve(resp.access_token); }
        };
        client.requestAccessToken({ prompt: this.accessToken ? "" : "consent" });
      } catch (e) { reject(e); }
    });
  },

  async withToken() {
    if (this.accessToken) return this.accessToken;
    return this.connect();
  },

  async appendToSheet(values, range) {
    const token = await this.withToken();
    const sheetId = DB.settings.sheetId;
    if (!sheetId) throw new Error("No Google Sheet ID configured in Settings.");
    const r = range || "Sheet1!A1";
    const url = `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(sheetId)}/values/${encodeURIComponent(r)}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`;
    const resp = await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ values: [values] }),
    });
    if (!resp.ok) throw new Error(`Sheets API error ${resp.status}: ${await resp.text()}`);
    return resp.json();
  },

  async uploadTextToDrive(filename, text) {
    const token = await this.withToken();
    const metadata = { name: filename, mimeType: "text/plain" };
    if (DB.settings.driveFolderId) metadata.parents = [DB.settings.driveFolderId];
    const boundary = "rucva-" + uid();
    const body =
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(metadata)}\r\n` +
      `--${boundary}\r\nContent-Type: text/plain\r\n\r\n${text}\r\n--${boundary}--`;
    const resp = await fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/related; boundary=${boundary}` },
      body,
    });
    if (!resp.ok) throw new Error(`Drive API error ${resp.status}: ${await resp.text()}`);
    return resp.json();
  },

  async listDriveFiles() {
    const token = await this.withToken();
    let q = "trashed = false";
    if (DB.settings.driveFolderId) q += ` and '${DB.settings.driveFolderId}' in parents`;
    const url = `https://www.googleapis.com/drive/v3/files?q=${encodeURIComponent(q)}&fields=files(id,name,webViewLink,modifiedTime)&orderBy=modifiedTime desc&pageSize=25`;
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) throw new Error(`Drive API error ${resp.status}: ${await resp.text()}`);
    return (await resp.json()).files || [];
  },
};

/* ============================================================
   Speech (Web Speech API) — client-side only, Chrome-best support
   ============================================================ */

const Speech = {
  recognition: null,
  supported() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); },
  ttsSupported() { return "speechSynthesis" in window; },
  listen(onResult, onEnd) {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) return false;
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => onResult(e.results[0][0].transcript);
    rec.onend = onEnd;
    rec.onerror = onEnd;
    rec.start();
    this.recognition = rec;
    return true;
  },
  stop() { if (this.recognition) this.recognition.stop(); },
  speak(text) {
    if (!this.ttsSupported() || !DB.settings.ttsEnabled) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 3000));
    u.rate = 1.03;
    window.speechSynthesis.speak(u);
  },
};

/* ============================================================
   Sections
   ============================================================ */

const SECTIONS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "chat", label: "AI Chat" },
  { id: "analyzer", label: "Product Analyzer" },
  { id: "cogs", label: "COGS Tracker" },
  { id: "sourcing", label: "Sourcing Assistant" },
  { id: "tasks", label: "Daily Tasks" },
  { id: "metrics", label: "Metrics" },
  { id: "calculator", label: "Calculator" },
  { id: "ungating", label: "Ungating Tracker" },
  { id: "settings", label: "Settings" },
];

let currentSection = "dashboard";

function buildNav() {
  const nav = document.getElementById("navlist");
  nav.innerHTML = "";
  SECTIONS.forEach((s) => {
    const btn = el("button", { class: "navbtn" + (s.id === currentSection ? " active" : ""), onclick: () => goTo(s.id) }, [
      el("span", { class: "dot" }), s.label,
    ]);
    btn.dataset.section = s.id;
    nav.appendChild(btn);
  });
}

function goTo(sectionId) {
  currentSection = sectionId;
  document.querySelectorAll(".navbtn").forEach((b) => b.classList.toggle("active", b.dataset.section === sectionId));
  document.getElementById("pageTitle").textContent = SECTIONS.find((s) => s.id === sectionId).label;
  document.getElementById("sidebar").classList.remove("open");
  renderSection(sectionId);
}

function renderSection(id) {
  const content = document.getElementById("content");
  content.innerHTML = "";
  const renderers = {
    dashboard: renderDashboard, chat: renderChat, analyzer: renderAnalyzer, cogs: renderCogs,
    sourcing: renderSourcing, tasks: renderTasks, metrics: renderMetrics, calculator: renderCalculator,
    ungating: renderUngating, settings: renderSettings,
  };
  renderers[id](content);
}

/* ---------- Dashboard ---------- */

function monthKey(d) { return d.slice(0, 7); }
function shiftMonthKey(key, delta) {
  const [y, m] = key.split("-").map(Number);
  const total = y * 12 + (m - 1) + delta;
  const ny = Math.floor(total / 12), nm = (total % 12) + 1;
  return `${ny}-${String(nm).padStart(2, "0")}`;
}

function renderDashboard(root) {
  const today = todayISO();
  const thisMonth = monthKey(today);
  const todayEntry = DB.metrics.find((m) => m.date === today);
  const monthEntries = DB.metrics.filter((m) => monthKey(m.date) === thisMonth);
  const monthProfit = round2(monthEntries.reduce((s, m) => s + (m.profit || 0), 0));
  const monthUnits = monthEntries.reduce((s, m) => s + (m.units || 0), 0);
  const goal = DB.settings.monthlyGoal || 0;
  const goalPct = goal ? Math.min(100, round2((monthProfit / goal) * 100, 1)) : 0;
  const activeInventory = DB.products.reduce((s, p) => s + (Number(p.unitsRemaining) || 0), 0);
  const tasksToday = DB.tasks.filter((t) => !t.done && t.dueDate === today);
  const overdueTasks = DB.tasks.filter((t) => !t.done && t.dueDate && t.dueDate < today);

  root.appendChild(el("div", { class: "banner good" }, [
    `Goal check: $${monthProfit.toLocaleString()} of $${goal.toLocaleString()} this month (${goalPct}%). ` +
    (goalPct >= 100 ? "Goal hit — raise it." : goalPct >= 60 ? "On pace, keep sourcing." : "Behind pace — source or reprice this week."),
  ]));

  const grid = el("div", { class: "grid cols-4" });
  grid.appendChild(statCard("Today's Revenue", fmtMoney(todayEntry?.revenue), null));
  grid.appendChild(statCard("Today's Profit", fmtMoney(todayEntry?.profit), todayEntry?.profit > 0 ? "good" : null));
  grid.appendChild(statCard("Units Sold (Month)", monthUnits.toLocaleString(), null, `Goal progress ${goalPct}%`));
  grid.appendChild(statCard("Active Inventory", activeInventory.toLocaleString() + " units", null, DB.products.length + " SKUs tracked"));
  root.appendChild(grid);

  const progressCard = el("div", { class: "card section", style: "margin-top:16px;" }, [
    el("div", { class: "flex-between" }, [el("div", { class: "section-title" }, ["Monthly Profit Goal"]), el("span", { class: "mono" }, [`${fmtMoney(monthProfit)} / ${fmtMoney(goal)}`])]),
    el("div", { class: "progress", style: "margin-top:10px;" }, [el("div", { style: `width:${goalPct}%` })]),
  ]);
  root.appendChild(progressCard);

  const row = el("div", { class: "grid cols-2", style: "margin-top:16px;" });

  const taskCard = el("div", { class: "card section" });
  taskCard.appendChild(el("div", { class: "section-title" }, [`Tasks Due Today (${tasksToday.length})`]));
  if (overdueTasks.length) taskCard.appendChild(el("div", { class: "banner bad" }, [`${overdueTasks.length} overdue task(s) — see Daily Tasks.`]));
  if (!tasksToday.length) taskCard.appendChild(el("div", { class: "empty" }, ["Nothing due today."]));
  tasksToday.forEach((t) => taskCard.appendChild(el("div", { style: "padding:6px 0;border-bottom:1px solid var(--border);font-size:13px;" }, [`• ${t.text}`])));
  taskCard.appendChild(el("button", { class: "btn btn-ghost btn-sm", style: "margin-top:10px;", onclick: () => goTo("tasks") }, ["Open Task Manager →"]));
  row.appendChild(taskCard);

  const quickCard = el("div", { class: "card section" });
  quickCard.appendChild(el("div", { class: "section-title" }, ["Quick Access"]));
  const quickGrid = el("div", { style: "display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;" });
  ["chat", "analyzer", "cogs", "sourcing", "metrics", "calculator"].forEach((id) => {
    const s = SECTIONS.find((x) => x.id === id);
    quickGrid.appendChild(el("button", { class: "btn btn-ghost btn-sm", onclick: () => goTo(id) }, [s.label]));
  });
  quickCard.appendChild(quickGrid);
  row.appendChild(quickCard);

  root.appendChild(row);

  const lowStock = DB.products.filter((p) => Number(p.unitsRemaining) <= 5 && p.status !== "Sold Out");
  if (lowStock.length) {
    root.appendChild(el("div", { class: "banner warn", style: "margin-top:16px;" }, [`Low stock: ${lowStock.map((p) => p.name || "unnamed").join(", ")} — check COGS Tracker.`]));
  }
}

function statCard(label, value, tone, sub) {
  return el("div", { class: "card" }, [
    el("div", { class: "stat-label" }, [label]),
    el("div", { class: "stat-value" + (tone ? " " + tone : "") }, [value]),
    sub ? el("div", { class: "stat-sub" }, [sub]) : null,
  ]);
}

/* ---------- AI Chat ---------- */

function renderChat(root) {
  const panel = el("div", { class: "card section", id: "chatPanel" });
  const log = el("div", { id: "chatLog" });
  const bar = el("div", { id: "chatInputBar" });
  const textarea = el("textarea", { id: "chatInput", placeholder: "Ask about a product, Keepa data, sourcing, pricing, ungating…", rows: "1" });
  const micBtn = el("button", { id: "micBtn", type: "button", title: "Voice input" }, ["🎤"]);
  const speakToggle = el("button", { id: "speakToggle", type: "button", title: "Read replies aloud", class: DB.settings.ttsEnabled ? "on" : "" }, ["🔊"]);
  const sendBtn = el("button", { id: "sendBtn", class: "btn btn-navy", type: "button" }, ["Send"]);

  bar.appendChild(textarea);
  if (Speech.supported()) bar.appendChild(micBtn); else micBtn.style.display = "none";
  if (Speech.ttsSupported()) bar.appendChild(speakToggle); else speakToggle.style.display = "none";
  bar.appendChild(sendBtn);

  panel.appendChild(log);
  panel.appendChild(bar);
  root.appendChild(panel);

  if (!DB.chat.length) {
    addChatNotice(log, "RUCVA is ready. Ask about a sourcing decision, paste Keepa numbers, or ask it to work through a product with you.");
  } else {
    DB.chat.forEach((m) => addChatBubble(log, m.role, m.content));
  }

  function send() {
    const text = textarea.value.trim();
    if (!text) return;
    textarea.value = "";
    autoGrow();
    runChatTurn(log, text);
  }
  sendBtn.addEventListener("click", send);
  textarea.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  function autoGrow() { textarea.style.height = "auto"; textarea.style.height = Math.min(textarea.scrollHeight, 140) + "px"; }
  textarea.addEventListener("input", autoGrow);

  micBtn.addEventListener("click", () => {
    if (micBtn.classList.contains("listening")) { Speech.stop(); return; }
    micBtn.classList.add("listening");
    Speech.listen((transcript) => { textarea.value = transcript; autoGrow(); }, () => micBtn.classList.remove("listening"));
  });
  speakToggle.addEventListener("click", () => {
    DB.settings.ttsEnabled = !DB.settings.ttsEnabled;
    saveDB();
    speakToggle.classList.toggle("on", DB.settings.ttsEnabled);
  });

  log.scrollTop = log.scrollHeight;
}

function addChatBubble(log, role, text) {
  const row = el("div", { class: "chatrow " + role });
  const bubble = el("div", { class: "bubble" }, [text || ""]);
  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return bubble;
}
function addChatNotice(log, text) {
  log.appendChild(el("div", { class: "chat-notice" }, [text]));
}

async function runChatTurn(log, userText) {
  DB.chat.push({ role: "user", content: userText });
  saveDB();
  addChatBubble(log, "user", userText);

  const bubble = addChatBubble(log, "assistant", "");
  const toolNames = [];

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: DB.chat.slice(-30) }),
    });
    if (!resp.ok || !resp.body) throw new Error(`Server returned ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const evt = JSON.parse(line);
        if (evt.type === "delta") { fullText += evt.text; bubble.textContent = fullText; log.scrollTop = log.scrollHeight; }
        else if (evt.type === "tool") { toolNames.push(evt.name); }
        else if (evt.type === "error") { throw new Error(evt.message); }
      }
    }

    if (toolNames.length) {
      const chips = el("div", {});
      [...new Set(toolNames)].forEach((n) => chips.appendChild(el("span", { class: "chat-tool-chip" }, [n.replace(/_/g, " ")])));
      bubble.parentElement.appendChild(chips);
    }

    DB.chat.push({ role: "assistant", content: fullText });
    saveDB();
    Speech.speak(fullText);
  } catch (e) {
    if (!bubble.textContent) bubble.parentElement.remove();
    addChatNotice(log, "Error: " + e.message);
  }
}

/* ---------- Product Analyzer ---------- */

function renderAnalyzer(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Product Analyzer"]));
  card.appendChild(el("div", { class: "section-desc" }, ["Enter what you paid and what it sells for — get real FBA/FBM profit, ROI, margin, breakeven, and a Buy/Skip call."]));

  const form = el("form");
  const f = {};
  const addField = (parent, key, label, type, extra) => {
    const wrap = el("div", { class: "field" }, [el("label", {}, [label]), (f[key] = el("input", Object.assign({ type }, extra || {})))]);
    parent.appendChild(wrap);
  };

  const row1 = el("div", { class: "row" });
  addField(row1, "cost", "What did you pay for it? ($)", "number", { step: "0.01", required: "required" });
  addField(row1, "sellPrice", "Current Amazon sale price ($)", "number", { step: "0.01", required: "required" });
  form.appendChild(row1);

  const row2 = el("div", { class: "row" });
  addField(row2, "fbaSellerCount", "How many FBA sellers on the listing?", "number", { step: "1" });
  addField(row2, "bsr", "BSR (Best Sellers Rank)", "number", { step: "1" });
  form.appendChild(row2);

  const row3 = el("div", { class: "row" });
  addField(row3, "monthlySales", "Monthly sales estimate (units)", "number", { step: "1" });
  addField(row3, "weightOz", "Weight (oz, for FBA fee estimate)", "number", { step: "0.1" });
  form.appendChild(row3);

  const row4 = el("div", { class: "row" });
  const modeWrap = el("div", { class: "field" }, [el("label", {}, ["Fulfillment"]), (f.mode = el("select", {}, [el("option", { value: "FBA" }, ["FBA"]), el("option", { value: "FBM" }, ["FBM"])]))]);
  row4.appendChild(modeWrap);
  f.shippingCost = el("input", { type: "number", step: "0.01" });
  const shipWrap = el("div", { class: "field" }, [el("label", {}, ["Shipping cost (FBM only, $)"]), f.shippingCost]);
  row4.appendChild(shipWrap);
  form.appendChild(row4);

  const cbWrap = el("div", { class: "field checkbox-row" }, [(f.amazonOnListing = el("input", { type: "checkbox" })), el("span", {}, ["Amazon is on this listing"])]);
  form.appendChild(cbWrap);

  const nameRow = el("div", { class: "row" });
  f.name = el("input", { type: "text" }); nameRow.appendChild(el("div", { class: "field" }, [el("label", {}, ["Product name (optional)"]), f.name]));
  f.asin = el("input", { type: "text" }); nameRow.appendChild(el("div", { class: "field" }, [el("label", {}, ["ASIN (optional)"]), f.asin]));
  form.appendChild(nameRow);

  form.appendChild(el("button", { class: "btn btn-navy", type: "submit" }, ["Analyze"]));
  card.appendChild(form);

  const resultBox = el("div", { id: "analyzerResult", style: "margin-top:20px;" });
  card.appendChild(resultBox);
  root.appendChild(card);

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const cost = parseFloat(f.cost.value), sellPrice = parseFloat(f.sellPrice.value);
    const mode = f.mode.value;
    let result;
    try {
      result = mode === "FBA"
        ? calcFbaEconomics({ cost, sellPrice, weightOz: parseFloat(f.weightOz.value) || 8 })
        : calcFbmEconomics({ cost, sellPrice, shippingCost: parseFloat(f.shippingCost.value) || 0 });
    } catch (err) {
      resultBox.innerHTML = "";
      resultBox.appendChild(el("div", { class: "banner bad" }, [err.message]));
      return;
    }
    const risk = riskLevel({ fbaSellerCount: parseFloat(f.fbaSellerCount.value) || 0, amazonOnListing: f.amazonOnListing.checked, bsr: parseFloat(f.bsr.value) || 0 });

    const entry = {
      id: uid(), name: f.name.value || "(unnamed)", asin: f.asin.value || "",
      cost, sellPrice, mode, profit: result.netProfit, roi: result.roiPct, margin: result.marginPct,
      verdict: result.verdict, risk, date: todayISO(),
    };
    DB.analyzerLog.unshift(entry);
    saveDB();

    resultBox.innerHTML = "";
    const g = el("div", { class: "grid cols-4" });
    g.appendChild(statCard(mode + " Profit / Unit", fmtMoney(result.netProfit), result.netProfit > 0 ? "good" : "bad"));
    g.appendChild(statCard("ROI", fmtPct(result.roiPct)));
    g.appendChild(statCard("Margin", fmtPct(result.marginPct)));
    g.appendChild(statCard("Breakeven Price", fmtMoney(result.breakeven)));
    resultBox.appendChild(g);

    resultBox.appendChild(el("div", { class: "flex-between", style: "margin-top:16px;" }, [
      el("div", {}, [
        el("span", { class: "badge " + verdictBadgeClass(result.verdict), style: "font-size:14px;padding:6px 14px;" }, [result.verdict]),
        el("span", { class: "badge " + risk.toLowerCase(), style: "margin-left:8px;" }, [risk + " RISK"]),
      ]),
      el("div", { style: "display:flex;gap:8px;" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => addAnalyzerToCogs(entry, mode) }, ["Add to COGS Tracker"]),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => exportAnalyzerRow(entry) }, ["Export to Sheets"]),
      ]),
    ]));

    resultBox.appendChild(el("div", { class: "section-desc", style: "margin-top:10px;" }, [
      reasoningLine(result, risk),
    ]));
  });
}

function reasoningLine(result, risk) {
  if (result.verdict === "SKIP") return `Margin ${fmtPct(result.marginPct)} / ROI ${fmtPct(result.roiPct)} is below the 10%/20% floor — the math doesn't work at this cost/price. ${risk === "High" ? "Risk is also high — pass." : "Fix the price or find it cheaper before buying."}`;
  if (result.verdict === "MARGINAL") return `Margin ${fmtPct(result.marginPct)} / ROI ${fmtPct(result.roiPct)} clears the floor but isn't strong. ${risk === "High" ? "Combined with high competitive risk, lean toward skipping." : "Workable if you're confident in sell-through."}`;
  return `Margin ${fmtPct(result.marginPct)} / ROI ${fmtPct(result.roiPct)} clears your minimums. ${risk === "High" ? "Watch the risk level though — heavy competition or Amazon on the listing." : "Risk looks manageable."}`;
}

function addAnalyzerToCogs(entry, mode) {
  DB.products.push({
    id: uid(), name: entry.name, asin: entry.asin, units: 1, costPerUnit: entry.cost,
    salePrice: entry.sellPrice, mode, shippingCost: 0, unitsRemaining: 1, status: "In Stock", lastUpdated: todayISO(),
  });
  saveDB();
  alert("Added to COGS Tracker.");
}

async function exportAnalyzerRow(entry) {
  try {
    await Google.appendToSheet([entry.date, entry.name, entry.asin, entry.cost, entry.sellPrice, entry.mode, entry.profit, entry.roi, entry.verdict]);
    alert("Logged to Google Sheets.");
  } catch (e) { alert("Sheets export failed: " + e.message); }
}

/* ---------- COGS Tracker ---------- */

const COGS_STATUSES = ["In Stock", "Low Stock", "Sold Out", "At Amazon"];

function renderCogs(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Cost of Goods Tracker"]));
  card.appendChild(el("div", { class: "section-desc" }, ["Spreadsheet-style — edit any cell, totals and profit recalculate automatically."]));

  const actions = el("div", { class: "table-actions" }, [
    el("button", { class: "btn btn-navy btn-sm", onclick: () => { DB.products.push(blankProduct()); saveDB(); renderSection("cogs"); } }, ["+ Add Product"]),
    el("button", { class: "btn btn-ghost btn-sm", onclick: exportCogsCsv }, ["Export CSV"]),
    el("button", { class: "btn btn-ghost btn-sm", onclick: exportCogsSheets }, ["Export to Google Sheets"]),
  ]);
  card.appendChild(actions);

  const wrap = el("div", { class: "table-wrap" });
  const table = el("table", { class: "data" });
  table.appendChild(el("thead", {}, [el("tr", {}, [
    "Product", "ASIN", "Units", "Cost/Unit", "Total COGS", "Sale Price", "Mode", "Profit/Unit", "Total Profit", "Remaining", "Status", "",
  ].map((h) => el("th", {}, [h])))]));

  const tbody = el("tbody");
  if (!DB.products.length) {
    tbody.appendChild(el("tr", {}, [el("td", { colspan: "12" }, [el("div", { class: "empty" }, ["No products yet — add one to start tracking."])])]));
  }

  let totalCogs = 0, totalProfitIfSold = 0;

  DB.products.forEach((p) => {
    const totalCogsRow = round2((Number(p.units) || 0) * (Number(p.costPerUnit) || 0));
    let profitPerUnit = 0;
    try {
      profitPerUnit = p.mode === "FBM"
        ? calcFbmEconomics({ cost: Number(p.costPerUnit) || 0, sellPrice: Number(p.salePrice) || 0, shippingCost: Number(p.shippingCost) || 0 }).netProfit
        : calcFbaEconomics({ cost: Number(p.costPerUnit) || 0, sellPrice: Number(p.salePrice) || 0 }).netProfit;
    } catch (e) { profitPerUnit = 0; }
    const totalProfitRow = round2(profitPerUnit * (Number(p.units) || 0));
    totalCogs += totalCogsRow;
    totalProfitIfSold += totalProfitRow;

    const belowMin = DB.settings.minMarginPct && p.salePrice > 0 && round2((profitPerUnit / p.salePrice) * 100) < DB.settings.minMarginPct;

    const tr = el("tr", {});
    const textCell = (key, type) => {
      const input = el("input", { type: type || "text", value: p[key] ?? "" });
      input.addEventListener("change", () => { p[key] = type === "number" ? parseFloat(input.value) || 0 : input.value; p.lastUpdated = todayISO(); saveDB(); renderSection("cogs"); });
      return el("td", {}, [input]);
    };
    tr.appendChild(textCell("name"));
    tr.appendChild(textCell("asin"));
    tr.appendChild(textCell("units", "number"));
    tr.appendChild(textCell("costPerUnit", "number"));
    tr.appendChild(el("td", { class: "mono" }, [fmtMoney(totalCogsRow)]));
    tr.appendChild(textCell("salePrice", "number"));
    const modeSel = el("select", {}, ["FBA", "FBM"].map((m) => el("option", { value: m, selected: p.mode === m ? "selected" : null }, [m])));
    modeSel.addEventListener("change", () => { p.mode = modeSel.value; saveDB(); renderSection("cogs"); });
    tr.appendChild(el("td", {}, [modeSel]));
    tr.appendChild(el("td", { class: "mono" + (belowMin ? "" : "") }, [belowMin ? el("span", { style: "color:var(--bad);font-weight:700;" }, [fmtMoney(profitPerUnit)]) : fmtMoney(profitPerUnit)]));
    tr.appendChild(el("td", { class: "mono" }, [fmtMoney(totalProfitRow)]));
    tr.appendChild(textCell("unitsRemaining", "number"));
    const statusSel = el("select", {}, COGS_STATUSES.map((s) => el("option", { value: s, selected: p.status === s ? "selected" : null }, [s])));
    statusSel.addEventListener("change", () => { p.status = statusSel.value; saveDB(); renderSection("cogs"); });
    tr.appendChild(el("td", {}, [statusSel]));
    tr.appendChild(el("td", {}, [el("button", { class: "icon-x", title: "Delete", onclick: () => { DB.products = DB.products.filter((x) => x.id !== p.id); saveDB(); renderSection("cogs"); } }, ["✕"])]));
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  table.appendChild(el("tfoot", {}, [el("tr", {}, [
    el("td", { colspan: "4" }, ["Totals"]), el("td", { class: "mono" }, [fmtMoney(totalCogs)]),
    el("td", { colspan: "3" }, []), el("td", { class: "mono" }, [fmtMoney(totalProfitIfSold)]), el("td", { colspan: "3" }, []),
  ])]));

  wrap.appendChild(table);
  card.appendChild(wrap);
  root.appendChild(card);
}

function blankProduct() {
  return { id: uid(), name: "", asin: "", units: 0, costPerUnit: 0, salePrice: 0, mode: "FBA", shippingCost: 0, unitsRemaining: 0, status: "In Stock", lastUpdated: todayISO() };
}

function exportCogsCsv() {
  const cols = [
    { key: "name", label: "Product" }, { key: "asin", label: "ASIN" }, { key: "units", label: "Units" },
    { key: "costPerUnit", label: "Cost/Unit" }, { key: "salePrice", label: "Sale Price" }, { key: "mode", label: "Mode" },
    { key: "unitsRemaining", label: "Remaining" }, { key: "status", label: "Status" },
  ];
  downloadFile("cogs-tracker.csv", toCsv(DB.products, cols), "text/csv");
}

async function exportCogsSheets() {
  try {
    for (const p of DB.products) {
      await Google.appendToSheet([p.name, p.asin, p.units, p.costPerUnit, p.salePrice, p.mode, p.unitsRemaining, p.status]);
    }
    alert("COGS tracker exported to Google Sheets.");
  } catch (e) { alert("Sheets export failed: " + e.message); }
}

/* ---------- Sourcing Assistant ---------- */

function renderSourcing(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Sourcing Assistant"]));
  card.appendChild(el("div", { class: "section-desc" }, ["Set up a sourcing session — get Keepa filter settings, a checklist, and a running tally."]));

  const form = el("form", { class: "row" });
  const budget = el("input", { type: "number", step: "1", placeholder: "e.g. 500" });
  const category = el("input", { type: "text", placeholder: "e.g. Kitchen" });
  const minProfit = el("input", { type: "number", step: "0.01", placeholder: "e.g. 5.00" });
  const fulfillment = el("select", {}, [el("option", { value: "FBA" }, ["FBA"]), el("option", { value: "FBM" }, ["FBM"])]);
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Budget ($)"]), budget]));
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Target category"]), category]));
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Min profit/unit ($)"]), minProfit]));
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Fulfillment"]), fulfillment]));
  const genBtn = el("button", { class: "btn btn-navy", type: "button", style: "align-self:flex-end;height:38px;" }, ["Generate Plan"]);
  form.appendChild(genBtn);
  card.appendChild(form);

  const out = el("div", { id: "sourcingOut", style: "margin-top:18px;" });
  card.appendChild(out);
  root.appendChild(card);

  genBtn.addEventListener("click", () => {
    out.innerHTML = "";
    const b = parseFloat(budget.value) || 0, cat = category.value || "any category", mp = parseFloat(minProfit.value) || 3;

    const keepaCard = el("div", { class: "card", style: "margin-bottom:14px;" });
    keepaCard.appendChild(el("div", { class: "section-title" }, ["Keepa Product Finder — suggested filters"]));
    const keepaList = [
      `Category: ${cat}`,
      `Buy Box price: $${Math.max(8, Math.round(mp * 4))} – $${Math.max(20, Math.round(b / 3 || 60))}`,
      "Sales rank drops (30 days): 10+ (signals real velocity)",
      "Sales rank current: under 150,000 for most categories (adjust for niche size)",
      "Review count: under 500 if you need room to compete; ignore this filter if you have a strong differentiation angle",
      "FBA sellers on listing: 1–8 (double check Amazon-on-listing status manually — Keepa's filter is unreliable here)",
      "Buy Box % Amazon 365 days: exclude near-100% (means Amazon is the default seller most of the time)",
    ];
    keepaCard.appendChild(el("ul", { style: "margin:8px 0 0;padding-left:20px;font-size:13px;line-height:1.7;" }, keepaList.map((x) => el("li", {}, [x]))));
    out.appendChild(keepaCard);

    const checklistCard = el("div", { class: "card", style: "margin-bottom:14px;" });
    checklistCard.appendChild(el("div", { class: "section-title" }, ["Sourcing Session Checklist"]));
    const checklist = [
      "Check 90-day and 180-day Keepa price average — is current price above or below average?",
      "Check BSR trend — improving, flat, or declining over the last 90 days?",
      "Check who owns the Buy Box and how often it rotates",
      "Confirm the category/brand isn't gated, or that you're already approved",
      "Check for hazmat/meltable/oversize fee traps before committing",
      "Run the numbers in the Product Analyzer before buying — never eyeball margin",
      `Target: profit/unit at or above $${mp.toFixed(2)}, ROI at or above 20-30%`,
    ];
    checklistCard.appendChild(el("ul", { style: "margin:8px 0 0;padding-left:20px;font-size:13px;line-height:1.7;" }, checklist.map((x) => el("li", {}, [x]))));
    out.appendChild(checklistCard);

    const sellerAmpCard = el("div", { class: "card", style: "margin-bottom:14px;" });
    sellerAmpCard.appendChild(el("div", { class: "section-title" }, ["Before you buy — SellerAmp check"]));
    sellerAmpCard.appendChild(el("ul", { style: "margin:8px 0 0;padding-left:20px;font-size:13px;line-height:1.7;" }, [
      "IPI/restriction flags clear on the ASIN",
      "Sales estimate matches what Keepa's rank drops imply — big mismatch means one is wrong",
      "ROI and net profit after ALL fees (not just referral fee) clears your minimum",
      "Variation listings — check every variation's own BSR/price, not just the parent",
    ].map((x) => el("li", {}, [x]))));
    out.appendChild(sellerAmpCard);

    const sessionCard = el("div", { class: "card" });
    sessionCard.appendChild(el("div", { class: "flex-between" }, [
      el("div", { class: "section-title" }, ["This Session"]),
      el("button", { class: "btn btn-ghost btn-sm", onclick: () => { DB.sourcingSession = { count: 0, worthBuying: 0 }; saveDB(); renderSection("sourcing"); } }, ["New Session"]),
    ]));
    const statRow = el("div", { class: "grid cols-2", style: "margin-top:10px;" }, [
      statCard("Products Reviewed", DB.sourcingSession.count),
      statCard("Worth Buying", DB.sourcingSession.worthBuying),
    ]);
    sessionCard.appendChild(statRow);
    const btnRow = el("div", { style: "display:flex;gap:8px;margin-top:12px;" }, [
      el("button", { class: "btn btn-ghost btn-sm", onclick: () => { DB.sourcingSession.count++; saveDB(); renderSection("sourcing"); } }, ["+1 Reviewed"]),
      el("button", { class: "btn btn-gold btn-sm", onclick: () => { DB.sourcingSession.count++; DB.sourcingSession.worthBuying++; saveDB(); renderSection("sourcing"); } }, ["+1 Worth Buying"]),
    ]);
    sessionCard.appendChild(btnRow);
    out.appendChild(sessionCard);
  });
}

/* ---------- Daily Tasks ---------- */

const TASK_CATEGORIES = ["Ship Order", "FBA Shipment", "Restock", "Ungating Follow-up", "Settlement", "Other"];

function renderTasks(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Daily Task Manager"]));

  const lowStock = DB.products.filter((p) => Number(p.unitsRemaining) <= 5 && p.status !== "Sold Out");
  const stale = DB.products.filter((p) => p.lastUpdated && daysBetween(new Date(p.lastUpdated), new Date()) > 30 && p.status !== "Sold Out");
  if (lowStock.length) card.appendChild(el("div", { class: "banner warn" }, [`Restock alert: ${lowStock.map((p) => p.name || "unnamed").join(", ")} at 5 or fewer units.`]));
  if (stale.length) card.appendChild(el("div", { class: "banner warn" }, [`Sitting 30+ days without an update: ${stale.map((p) => p.name || "unnamed").join(", ")} — restock or consider clearing it.`]));

  const form = el("div", { class: "row" });
  const text = el("input", { type: "text", placeholder: "Task description" });
  const cat = el("select", {}, TASK_CATEGORIES.map((c) => el("option", { value: c }, [c])));
  const due = el("input", { type: "date", value: todayISO() });
  form.appendChild(el("div", { class: "field", style: "flex:2;" }, [el("label", {}, ["Task"]), text]));
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Category"]), cat]));
  form.appendChild(el("div", { class: "field" }, [el("label", {}, ["Due date"]), due]));
  const addBtn = el("button", { class: "btn btn-navy", type: "button", style: "align-self:flex-end;height:38px;" }, ["+ Add Task"]);
  form.appendChild(addBtn);
  card.appendChild(form);

  addBtn.addEventListener("click", () => {
    if (!text.value.trim()) return;
    DB.tasks.unshift({ id: uid(), text: text.value.trim(), category: cat.value, dueDate: due.value, done: false, createdAt: todayISO() });
    saveDB();
    renderSection("tasks");
  });

  const today = todayISO();
  const wrap = el("div", { class: "table-wrap", style: "margin-top:16px;" });
  const table = el("table", { class: "data" });
  table.appendChild(el("thead", {}, [el("tr", {}, ["Done", "Task", "Category", "Due", "Status", ""].map((h) => el("th", {}, [h])))]));
  const tbody = el("tbody");
  const sorted = [...DB.tasks].sort((a, b) => (a.done - b.done) || (a.dueDate || "").localeCompare(b.dueDate || ""));
  if (!sorted.length) tbody.appendChild(el("tr", {}, [el("td", { colspan: "6" }, [el("div", { class: "empty" }, ["No tasks yet."])])]));

  sorted.forEach((t) => {
    const overdue = !t.done && t.dueDate && t.dueDate < today;
    const tr = el("tr", {});
    const cb = el("input", { type: "checkbox" }); cb.checked = t.done;
    cb.addEventListener("change", () => { t.done = cb.checked; saveDB(); renderSection("tasks"); });
    tr.appendChild(el("td", {}, [cb]));
    tr.appendChild(el("td", { style: t.done ? "text-decoration:line-through;color:var(--text-muted);" : "" }, [t.text]));
    tr.appendChild(el("td", {}, [t.category]));
    tr.appendChild(el("td", { class: "mono" }, [t.dueDate || "—"]));
    tr.appendChild(el("td", {}, [t.done ? el("span", { class: "badge good" }, ["Done"]) : overdue ? el("span", { class: "badge urgent" }, ["Overdue"]) : el("span", { class: "badge neutral" }, ["Open"])]));
    tr.appendChild(el("td", {}, [el("button", { class: "icon-x", onclick: () => { DB.tasks = DB.tasks.filter((x) => x.id !== t.id); saveDB(); renderSection("tasks"); } }, ["✕"])]));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  card.appendChild(wrap);
  root.appendChild(card);
}

/* ---------- Metrics ---------- */

function renderMetrics(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Business Metrics"]));

  const form = el("div", { class: "row" });
  const date = el("input", { type: "date", value: todayISO() });
  const revenue = el("input", { type: "number", step: "0.01" });
  const profit = el("input", { type: "number", step: "0.01" });
  const units = el("input", { type: "number", step: "1" });
  const fbaRevenue = el("input", { type: "number", step: "0.01" });
  const fbmRevenue = el("input", { type: "number", step: "0.01" });
  [["Date", date], ["Revenue", revenue], ["Profit", profit], ["Units", units], ["FBA Revenue", fbaRevenue], ["FBM Revenue", fbmRevenue]].forEach(([label, input]) => {
    form.appendChild(el("div", { class: "field" }, [el("label", {}, [label]), input]));
  });
  const saveBtn = el("button", { class: "btn btn-navy", type: "button", style: "align-self:flex-end;height:38px;" }, ["Save Day"]);
  form.appendChild(saveBtn);
  card.appendChild(form);

  saveBtn.addEventListener("click", () => {
    const d = date.value || todayISO();
    const entry = { date: d, revenue: parseFloat(revenue.value) || 0, profit: parseFloat(profit.value) || 0, units: parseInt(units.value) || 0, fbaRevenue: parseFloat(fbaRevenue.value) || 0, fbmRevenue: parseFloat(fbmRevenue.value) || 0 };
    DB.metrics = DB.metrics.filter((m) => m.date !== d);
    DB.metrics.push(entry);
    DB.metrics.sort((a, b) => a.date.localeCompare(b.date));
    saveDB();
    renderSection("metrics");
  });

  root.appendChild(card);
  if (!DB.metrics.length) { root.appendChild(el("div", { class: "empty" }, ["No daily numbers logged yet."])); return; }

  const today = new Date();
  const thisMonth = monthKey(todayISO());
  const lastMonthKey = shiftMonthKey(thisMonth, -1);

  const monthEntries = DB.metrics.filter((m) => monthKey(m.date) === thisMonth);
  const lastMonthEntries = DB.metrics.filter((m) => monthKey(m.date) === lastMonthKey);
  const weekAgo = new Date(); weekAgo.setDate(weekAgo.getDate() - 7);
  const weekEntries = DB.metrics.filter((m) => new Date(m.date) >= weekAgo);

  const monthProfit = round2(monthEntries.reduce((s, m) => s + m.profit, 0));
  const lastMonthProfit = round2(lastMonthEntries.reduce((s, m) => s + m.profit, 0));
  const weekProfit = round2(weekEntries.reduce((s, m) => s + m.profit, 0));
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const avgDaily = monthEntries.length ? monthProfit / monthEntries.length : 0;
  const projected = round2(avgDaily * daysInMonth);
  const fbaTotal = round2(monthEntries.reduce((s, m) => s + (m.fbaRevenue || 0), 0));
  const fbmTotal = round2(monthEntries.reduce((s, m) => s + (m.fbmRevenue || 0), 0));
  const momDelta = lastMonthProfit ? round2(((monthProfit - lastMonthProfit) / Math.abs(lastMonthProfit)) * 100) : null;

  const grid = el("div", { class: "grid cols-4", style: "margin-top:18px;" });
  grid.appendChild(statCard("Weekly Total (Profit)", fmtMoney(weekProfit)));
  grid.appendChild(statCard("Monthly Total (Profit)", fmtMoney(monthProfit)));
  grid.appendChild(statCard("Projected Month End", fmtMoney(projected), null, `based on ${fmtMoney(avgDaily)}/day avg`));
  grid.appendChild(statCard("Month over Month", momDelta == null ? "—" : (momDelta >= 0 ? "+" : "") + momDelta.toFixed(1) + "%", momDelta == null ? null : momDelta >= 0 ? "good" : "bad"));
  root.appendChild(grid);

  const split = el("div", { class: "card", style: "margin-top:16px;" });
  split.appendChild(el("div", { class: "section-title" }, ["FBA vs FBM Revenue (This Month)"]));
  const total = fbaTotal + fbmTotal || 1;
  split.appendChild(el("div", { class: "progress", style: "margin-top:10px;" }, [el("div", { style: `width:${(fbaTotal / total) * 100}%` })]));
  split.appendChild(el("div", { class: "stat-sub", style: "margin-top:6px;" }, [`FBA ${fmtMoney(fbaTotal)} · FBM ${fmtMoney(fbmTotal)}`]));
  root.appendChild(split);

  const chartCard = el("div", { class: "card", style: "margin-top:16px;" });
  chartCard.appendChild(el("div", { class: "section-title" }, ["Last 14 Days — Profit"]));
  const last14 = DB.metrics.slice(-14);
  const max = Math.max(1, ...last14.map((m) => m.profit));
  const bars = el("div", { class: "bars", style: "margin-top:14px;" });
  last14.forEach((m) => bars.appendChild(el("div", { class: "bar", style: `height:${Math.max(4, (m.profit / max) * 90)}px`, title: `${m.date}: ${fmtMoney(m.profit)}` }, [el("span", {})])));
  chartCard.appendChild(bars);
  root.appendChild(chartCard);

  const wrap = el("div", { class: "table-wrap card", style: "margin-top:16px;" });
  const table = el("table", { class: "data" });
  table.appendChild(el("thead", {}, [el("tr", {}, ["Date", "Revenue", "Profit", "Units", "FBA", "FBM"].map((h) => el("th", {}, [h])))]));
  const tbody = el("tbody");
  [...DB.metrics].reverse().slice(0, 30).forEach((m) => {
    tbody.appendChild(el("tr", {}, [
      el("td", { class: "mono" }, [m.date]), el("td", { class: "mono" }, [fmtMoney(m.revenue)]), el("td", { class: "mono" }, [fmtMoney(m.profit)]),
      el("td", { class: "mono" }, [String(m.units)]), el("td", { class: "mono" }, [fmtMoney(m.fbaRevenue)]), el("td", { class: "mono" }, [fmtMoney(m.fbmRevenue)]),
    ]));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  root.appendChild(wrap);
}

/* ---------- Calculator ---------- */

function renderCalculator(root) {
  const tabs = ["FBA Profit", "FBM Profit", "Gift Card Savings", "Loan/Credit ROI", "Q4 Compounding"];
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Financial Calculator"]));
  const tabBar = el("div", { style: "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;" });
  const out = el("div", { id: "calcOut" });
  let active = 0;
  function draw() {
    tabBar.innerHTML = "";
    tabs.forEach((t, i) => tabBar.appendChild(el("button", { class: "btn btn-sm " + (i === active ? "btn-navy" : "btn-ghost"), onclick: () => { active = i; draw(); } }, [t])));
    out.innerHTML = "";
    [calcTabFba, calcTabFbm, calcTabGiftCard, calcTabLoan, calcTabQ4][active](out);
  }
  card.appendChild(tabBar);
  card.appendChild(out);
  root.appendChild(card);
  draw();
}

function calcRow(labels) {
  const row = el("div", { class: "row" });
  const inputs = labels.map(([label, attrs]) => {
    const input = el("input", Object.assign({ type: "number", step: "0.01" }, attrs || {}));
    row.appendChild(el("div", { class: "field" }, [el("label", {}, [label]), input]));
    return input;
  });
  return { row, inputs };
}

function calcTabFba(out) {
  const { row, inputs } = calcRow(["Cost ($)", "Sale price ($)", "Weight (oz)"]);
  const [cost, price, weight] = inputs;
  const btn = el("button", { class: "btn btn-navy", type: "button" }, ["Calculate"]);
  const res = el("div", { style: "margin-top:14px;" });
  btn.addEventListener("click", () => {
    try {
      const r = calcFbaEconomics({ cost: parseFloat(cost.value) || 0, sellPrice: parseFloat(price.value) || 0, weightOz: parseFloat(weight.value) || 8 });
      res.innerHTML = "";
      res.appendChild(el("div", { class: "grid cols-4" }, [statCard("Profit", fmtMoney(r.netProfit)), statCard("ROI", fmtPct(r.roiPct)), statCard("Margin", fmtPct(r.marginPct)), statCard("Breakeven", fmtMoney(r.breakeven))]));
    } catch (e) { res.innerHTML = ""; res.appendChild(el("div", { class: "banner bad" }, [e.message])); }
  });
  out.appendChild(row); out.appendChild(btn); out.appendChild(res);
}

function calcTabFbm(out) {
  const { row, inputs } = calcRow(["Cost ($)", "Sale price ($)", "Shipping cost ($)"]);
  const [cost, price, ship] = inputs;
  const btn = el("button", { class: "btn btn-navy", type: "button" }, ["Calculate"]);
  const res = el("div", { style: "margin-top:14px;" });
  btn.addEventListener("click", () => {
    try {
      const r = calcFbmEconomics({ cost: parseFloat(cost.value) || 0, sellPrice: parseFloat(price.value) || 0, shippingCost: parseFloat(ship.value) || 0 });
      res.innerHTML = "";
      res.appendChild(el("div", { class: "grid cols-4" }, [statCard("Profit", fmtMoney(r.netProfit)), statCard("ROI", fmtPct(r.roiPct)), statCard("Margin", fmtPct(r.marginPct)), statCard("Breakeven", fmtMoney(r.breakeven))]));
    } catch (e) { res.innerHTML = ""; res.appendChild(el("div", { class: "banner bad" }, [e.message])); }
  });
  out.appendChild(row); out.appendChild(btn); out.appendChild(res);
}

function calcTabGiftCard(out) {
  const { row, inputs } = calcRow(["Face value ($)", "Discount %"]);
  const [face, disc] = inputs;
  const btn = el("button", { class: "btn btn-navy", type: "button" }, ["Calculate"]);
  const res = el("div", { style: "margin-top:14px;" });
  btn.addEventListener("click", () => {
    const f = parseFloat(face.value) || 0, d = parseFloat(disc.value) || 0;
    const paid = round2(f * (1 - d / 100));
    const savings = round2(f - paid);
    res.innerHTML = "";
    res.appendChild(el("div", { class: "grid cols-3" }, [statCard("You Pay", fmtMoney(paid)), statCard("Face Value", fmtMoney(f)), statCard("Savings", fmtMoney(savings), "good")]));
    res.appendChild(el("div", { class: "section-desc", style: "margin-top:10px;" }, [`Every $${f.toFixed(2)} of purchasing power costs you $${paid.toFixed(2)} — an effective ${d.toFixed(1)}% discount on whatever you buy with it.`]));
  });
  out.appendChild(row); out.appendChild(btn); out.appendChild(res);
}

function calcTabLoan(out) {
  const { row, inputs } = calcRow(["Loan amount ($)", "Annual interest rate (%)", "Inventory ROI per turn (%)", "Turns per year"]);
  const [amount, rate, roi, turns] = inputs;
  const btn = el("button", { class: "btn btn-navy", type: "button" }, ["Calculate"]);
  const res = el("div", { style: "margin-top:14px;" });
  btn.addEventListener("click", () => {
    const a = parseFloat(amount.value) || 0, r = parseFloat(rate.value) || 0, roiPct = parseFloat(roi.value) || 0, t = parseFloat(turns.value) || 1;
    const annualInterestCost = round2(a * (r / 100));
    const annualInventoryReturn = round2(a * (roiPct / 100) * t);
    const netBenefit = round2(annualInventoryReturn - annualInterestCost);
    res.innerHTML = "";
    res.appendChild(el("div", { class: "grid cols-3" }, [
      statCard("Annual Interest Cost", fmtMoney(annualInterestCost), "bad"),
      statCard("Annual Return from Capital", fmtMoney(annualInventoryReturn), "good"),
      statCard("Net Benefit", fmtMoney(netBenefit), netBenefit > 0 ? "good" : "bad"),
    ]));
    res.appendChild(el("div", { class: "banner " + (netBenefit > 0 ? "good" : "bad") }, [
      netBenefit > 0
        ? `Borrowing makes sense here — the inventory return beats the interest cost by ${fmtMoney(netBenefit)}/year. That's the math; your risk tolerance for debt is a separate call.`
        : `Borrowing does NOT make sense at these numbers — interest cost exceeds what the capital returns by ${fmtMoney(Math.abs(netBenefit))}/year.`,
    ]));
  });
  out.appendChild(row); out.appendChild(btn); out.appendChild(res);
}

function calcTabQ4(out) {
  const { row, inputs } = calcRow(["Starting capital ($)", "Monthly ROI (%)"]);
  const [capital, roi] = inputs;
  const btn = el("button", { class: "btn btn-navy", type: "button" }, ["Project to December"]);
  const res = el("div", { style: "margin-top:14px;" });
  btn.addEventListener("click", () => {
    const c0 = parseFloat(capital.value) || 0, r = (parseFloat(roi.value) || 0) / 100;
    const now = new Date();
    const monthsLeft = Math.max(1, 12 - now.getMonth());
    let c = c0;
    const rows = [];
    for (let i = 1; i <= monthsLeft; i++) { c = round2(c * (1 + r)); rows.push({ month: i, capital: c }); }
    res.innerHTML = "";
    res.appendChild(el("div", { class: "grid cols-3" }, [
      statCard("Starting Capital", fmtMoney(c0)), statCard(`Projected (${monthsLeft} mo.)`, fmtMoney(c), "good"),
      statCard("Total Growth", fmtMoney(round2(c - c0)), "good"),
    ]));
    const wrap = el("div", { class: "table-wrap", style: "margin-top:14px;" });
    const table = el("table", { class: "data" });
    table.appendChild(el("thead", {}, [el("tr", {}, ["Month", "Capital"].map((h) => el("th", {}, [h])))]));
    const tbody = el("tbody", {});
    rows.forEach((r2) => tbody.appendChild(el("tr", {}, [el("td", {}, [String(r2.month)]), el("td", { class: "mono" }, [fmtMoney(r2.capital)])])));
    table.appendChild(tbody);
    wrap.appendChild(table);
    res.appendChild(wrap);
  });
  out.appendChild(row); out.appendChild(btn); out.appendChild(res);
}

/* ---------- Ungating Tracker ---------- */

const UNGATING_STATUSES = ["Pending", "Approved", "Rejected"];

function renderUngating(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Ungating Tracker"]));

  const addBtn = el("button", { class: "btn btn-navy btn-sm", onclick: () => { DB.ungating.push({ id: uid(), brand: "", appliedDate: todayISO(), status: "Pending", submissions: 1, documents: "", followUpDate: "", notes: "" }); saveDB(); renderSection("ungating"); } }, ["+ Add Application"]);
  card.appendChild(el("div", { class: "table-actions" }, [addBtn]));

  const wrap = el("div", { class: "table-wrap" });
  const table = el("table", { class: "data" });
  table.appendChild(el("thead", {}, [el("tr", {}, ["Brand/Category", "Applied", "Status", "Submissions", "Documents", "Next Follow-up", "Notes", ""].map((h) => el("th", {}, [h])))]));
  const tbody = el("tbody");
  if (!DB.ungating.length) tbody.appendChild(el("tr", {}, [el("td", { colspan: "8" }, [el("div", { class: "empty" }, ["No applications tracked yet."])])]));

  const today = todayISO();
  DB.ungating.forEach((u) => {
    const tr = el("tr", {});
    const cell = (key, type) => {
      const input = el("input", { type: type || "text", value: u[key] ?? "" });
      input.addEventListener("change", () => { u[key] = type === "number" ? parseInt(input.value) || 0 : input.value; saveDB(); });
      return el("td", {}, [input]);
    };
    tr.appendChild(cell("brand"));
    tr.appendChild(cell("appliedDate", "date"));
    const statusSel = el("select", {}, UNGATING_STATUSES.map((s) => el("option", { value: s, selected: u.status === s ? "selected" : null }, [s])));
    statusSel.addEventListener("change", () => { u.status = statusSel.value; saveDB(); renderSection("ungating"); });
    tr.appendChild(el("td", {}, [statusSel]));
    tr.appendChild(cell("submissions", "number"));
    tr.appendChild(cell("documents"));
    const dueSoon = u.followUpDate && u.followUpDate <= today && u.status === "Pending";
    tr.appendChild(el("td", {}, [el("input", { type: "date", value: u.followUpDate || "", onchange: (e) => { u.followUpDate = e.target.value; saveDB(); renderSection("ungating"); } }), dueSoon ? el("span", { class: "badge urgent", style: "margin-left:6px;" }, ["Due"]) : null]));
    tr.appendChild(cell("notes"));
    tr.appendChild(el("td", {}, [el("button", { class: "icon-x", onclick: () => { DB.ungating = DB.ungating.filter((x) => x.id !== u.id); saveDB(); renderSection("ungating"); } }, ["✕"])]));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  card.appendChild(wrap);
  root.appendChild(card);
}

/* ---------- Settings ---------- */

function renderSettings(root) {
  const card = el("div", { class: "card section" });
  card.appendChild(el("div", { class: "section-title" }, ["Settings"]));

  const goalField = el("input", { type: "number", step: "1", value: DB.settings.monthlyGoal });
  const minMarginField = el("input", { type: "number", step: "0.1", value: DB.settings.minMarginPct });
  const row1 = el("div", { class: "row" });
  row1.appendChild(el("div", { class: "field" }, [el("label", {}, ["Monthly profit goal ($)"]), goalField]));
  row1.appendChild(el("div", { class: "field" }, [el("label", {}, ["Minimum margin threshold (%)"]), minMarginField]));
  card.appendChild(row1);
  card.appendChild(el("button", { class: "btn btn-navy btn-sm", onclick: () => { DB.settings.monthlyGoal = parseFloat(goalField.value) || 0; DB.settings.minMarginPct = parseFloat(minMarginField.value) || 0; saveDB(); alert("Saved."); } }, ["Save"]));

  card.appendChild(el("hr", { style: "margin:22px 0;border:none;border-top:1px solid var(--border);" }));
  card.appendChild(el("div", { class: "section-title" }, ["AI Chat (Anthropic)"]));
  card.appendChild(el("div", { class: "section-desc" }, ["Powered by the ANTHROPIC_API_KEY set in your Vercel project's environment variables — nothing to enter here. Use the button to confirm it's working."]));
  const testBtn = el("button", { class: "btn btn-ghost btn-sm", type: "button" }, ["Test Connection"]);
  const testOut = el("span", { class: "mono", style: "margin-left:10px;font-size:12px;" });
  testBtn.addEventListener("click", async () => {
    testOut.textContent = "checking…";
    try {
      const resp = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: [{ role: "user", content: "Reply with exactly: OK" }] }) });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      testOut.textContent = "✓ connected";
      testOut.style.color = "var(--good)";
    } catch (e) { testOut.textContent = "✗ " + e.message; testOut.style.color = "var(--bad)"; }
  });
  card.appendChild(el("div", {}, [testBtn, testOut]));

  card.appendChild(el("hr", { style: "margin:22px 0;border:none;border-top:1px solid var(--border);" }));
  card.appendChild(el("div", { class: "section-title" }, ["Google Sheets & Drive"]));
  card.appendChild(el("div", { class: "section-desc" }, ["Requires your own Google Cloud OAuth Client ID — see README for setup. No secret needed; this runs entirely in your browser."]));

  const clientIdField = el("input", { type: "text", value: DB.settings.googleClientId, placeholder: "xxxx.apps.googleusercontent.com" });
  const sheetIdField = el("input", { type: "text", value: DB.settings.sheetId, placeholder: "Spreadsheet ID from the sheet's URL" });
  const folderIdField = el("input", { type: "text", value: DB.settings.driveFolderId, placeholder: "Drive folder ID (optional)" });
  [["Google OAuth Client ID", clientIdField], ["Google Sheet ID", sheetIdField], ["Drive folder ID (optional)", folderIdField]].forEach(([label, input]) => {
    card.appendChild(el("div", { class: "field" }, [el("label", {}, [label]), input]));
  });
  const saveGoogleBtn = el("button", { class: "btn btn-navy btn-sm", type: "button" }, ["Save"]);
  const connectBtn = el("button", { class: "btn btn-gold btn-sm", type: "button", style: "margin-left:8px;" }, ["Connect Google Account"]);
  const googleStatus = el("span", { class: "mono", style: "margin-left:10px;font-size:12px;" });
  saveGoogleBtn.addEventListener("click", () => {
    DB.settings.googleClientId = clientIdField.value.trim();
    DB.settings.sheetId = sheetIdField.value.trim();
    DB.settings.driveFolderId = folderIdField.value.trim();
    saveDB();
    alert("Saved.");
  });
  connectBtn.addEventListener("click", async () => {
    googleStatus.textContent = "connecting…";
    try { await Google.connect(); googleStatus.textContent = "✓ connected"; googleStatus.style.color = "var(--good)"; }
    catch (e) { googleStatus.textContent = "✗ " + e.message; googleStatus.style.color = "var(--bad)"; }
  });
  card.appendChild(el("div", {}, [saveGoogleBtn, connectBtn, googleStatus]));

  root.appendChild(card);
}

/* ============================================================
   Init
   ============================================================ */

function init() {
  buildNav();
  goTo(currentSection);
  document.getElementById("topbarMeta").textContent = todayISO();
  document.getElementById("mobileToggle").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
}
init();
