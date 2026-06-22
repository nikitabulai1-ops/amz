const API_BASE = "http://localhost:8000";

function extractASIN() {
  const match = window.location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/);
  return match ? match[1] : null;
}

function createPanel() {
  const panel = document.createElement("div");
  panel.id = "apa-panel";
  panel.innerHTML = `
    <div id="apa-header">
      <span>Product Analyzer</span>
      <button id="apa-toggle">_</button>
    </div>
    <div id="apa-body">
      <div id="apa-cost-row">
        <label>Your Cost $</label>
        <input type="number" id="apa-cost" step="0.01" min="0" value="0" />
        <button id="apa-refresh">Analyze</button>
      </div>
      <div id="apa-results"><p class="apa-muted">Click Analyze to start</p></div>
    </div>
  `;
  document.body.appendChild(panel);

  document.getElementById("apa-toggle").addEventListener("click", () => {
    const body = document.getElementById("apa-body");
    body.style.display = body.style.display === "none" ? "block" : "none";
  });

  document.getElementById("apa-refresh").addEventListener("click", () => {
    const cost = parseFloat(document.getElementById("apa-cost").value) || 0;
    fetchAnalysis(cost);
  });
}

async function fetchAnalysis(cost) {
  const asin = extractASIN();
  if (!asin) {
    showResults("<p class='apa-error'>Could not detect ASIN</p>");
    return;
  }
  showResults("<p class='apa-muted'>Loading...</p>");

  try {
    const resp = await fetch(`${API_BASE}/analyze/${asin}?cost=${cost}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderResults(data);
  } catch (e) {
    showResults(`<p class='apa-error'>Error: ${e.message}. Is the backend running?</p>`);
  }
}

function renderResults(data) {
  const k = data.keepa || {};
  const s = data.selleramp || {};

  let html = "<table class='apa-table'>";

  if (k.title) html += row("Title", k.title);
  if (k.brand) html += row("Brand", k.brand);
  if (k.category) html += row("Category", k.category);
  if (k.salesRankCurrent != null && k.salesRankCurrent !== -1)
    html += row("BSR", k.salesRankCurrent.toLocaleString());
  if (k.currentPrice != null) html += row("Current Price", `$${k.currentPrice.toFixed(2)}`);
  if (k.avgPrice30 != null) html += row("Avg Price (30d)", `$${k.avgPrice30.toFixed(2)}`);
  if (k.avgPrice90 != null) html += row("Avg Price (90d)", `$${k.avgPrice90.toFixed(2)}`);
  if (k.monthlySold != null) html += row("Monthly Sold", k.monthlySold.toLocaleString());
  if (k.numberOfOffers != null) html += row("# of Offers", k.numberOfOffers);

  if (s.roi != null) html += row("ROI", `${s.roi}%`, s.roi >= 30 ? "apa-green" : s.roi >= 10 ? "apa-yellow" : "apa-red");
  if (s.profit != null) html += row("Profit", `$${s.profit}`);
  if (s.fbaFees != null) html += row("FBA Fees", `$${s.fbaFees}`);
  if (s.referralFee != null) html += row("Referral Fee", `$${s.referralFee}`);
  if (s.netRevenue != null) html += row("Net Revenue", `$${s.netRevenue}`);
  if (s.breakEvenCost != null) html += row("Break-Even Cost", `$${s.breakEvenCost}`);

  html += "</table>";

  if (data.errors) {
    html += "<div class='apa-errors'>";
    for (const [src, msg] of Object.entries(data.errors)) {
      html += `<p class='apa-error'>${src}: ${msg}</p>`;
    }
    html += "</div>";
  }

  showResults(html);
}

function row(label, value, cls) {
  return `<tr><td class="apa-label">${label}</td><td class="${cls || ''}">${value}</td></tr>`;
}

function showResults(html) {
  document.getElementById("apa-results").innerHTML = html;
}

createPanel();
