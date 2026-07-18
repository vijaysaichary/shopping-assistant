const form = document.getElementById("searchForm");
const queryInput = document.getElementById("query");
const chatArea = document.getElementById("chatArea");
const budgetRange = document.getElementById("budgetRange");
const budgetValue = document.getElementById("budgetValue");
const recentSearchesEl = document.getElementById("recentSearches");
const avatarBtn = document.getElementById("avatarBtn");
const avatarMenu = document.getElementById("avatarMenu");
const micBtn = document.getElementById("micBtn");

const RECENT_KEY = "shopping_assistant_recent_searches";

// Product Comparison (Module 7) state: which products are checked for
// comparison (key -> full product object, so /compare can be sent the exact
// already-fetched data statelessly) and a lookup of every product object
// seen so far this session, so a checkbox change handler can find the full
// object for whatever key it was ticked against.
const compareSelection = new Map();
const productLookup = new Map();
const MAX_COMPARE = 5;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function getRecentSearches() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY)) || [];
  } catch {
    return [];
  }
}

function saveRecentSearch(query) {
  let recent = getRecentSearches().filter((q) => q.toLowerCase() !== query.toLowerCase());
  recent.unshift(query);
  recent = recent.slice(0, 6);
  localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
  renderRecentSearches();
}

function renderRecentSearches() {
  const recent = getRecentSearches();
  if (!recent.length) {
    recentSearchesEl.innerHTML = "";
    return;
  }
  recentSearchesEl.innerHTML =
    "Recent: " +
    recent.map((q) => `<span class="tag" data-query="${escapeHtml(q)}">${escapeHtml(q)}</span>`).join("");
}

function appendUserMessage(text) {
  const msg = document.createElement("div");
  msg.className = "msg user";
  msg.innerHTML = `
    <div class="bubble-avatar">🧑</div>
    <div class="msg-content">
      <div class="bubble">${escapeHtml(text)}</div>
      <div class="timestamp">${formatTime()}</div>
    </div>`;
  chatArea.appendChild(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "end" });
}

function appendAiMessage(text) {
  const msg = document.createElement("div");
  msg.className = "msg ai";
  msg.innerHTML = `
    <div class="bubble-avatar">🤖</div>
    <div class="msg-content">
      <div class="bubble">${escapeHtml(text)}</div>
      <div class="timestamp">${formatTime()}</div>
    </div>`;
  chatArea.appendChild(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "end" });
}

function appendTypingMessage() {
  const msg = document.createElement("div");
  msg.className = "msg ai";
  msg.id = "typingMsg";
  msg.innerHTML = `
    <div class="bubble-avatar">🤖</div>
    <div class="msg-content">
      <div class="bubble">
        <div class="typing-dots"><span></span><span></span><span></span></div>
      </div>
    </div>`;
  chatArea.appendChild(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "end" });
  return msg;
}

function extractSummaryLines(reply) {
  if (!reply) return [];
  return reply
    .split("\n")
    .filter((line) => /^Best (overall|budget|performance) choice:/i.test(line.trim()));
}

function extractHeadline(reply) {
  if (!reply) return "";
  const firstLine = reply.split("\n")[0] || "";
  return firstLine;
}

function skeletonGrid(count) {
  return `<div class="product-grid">${Array.from({ length: count })
    .map(
      () => `
      <div class="skeleton-card">
        <div class="sk-img"></div>
        <div class="sk-line" style="width:80%"></div>
        <div class="sk-line" style="width:50%"></div>
        <div class="sk-line" style="width:65%"></div>
      </div>`
    )
    .join("")}</div>`;
}

function trustScoreColor(score) {
  if (score >= 80) return "var(--success)";
  if (score >= 50) return "var(--warning)";
  return "var(--danger)";
}

function trustScoreBadge(p) {
  const score = p.trust_score;
  if (score == null) return "";

  const confidence = p.trust_confidence || "Low";
  const color = trustScoreColor(score);
  const reasonParts = [p.trust_reason];
  if (p.trust_fake_review_probability != null) {
    reasonParts.push(`Estimated fake-review probability: ${Math.round(p.trust_fake_review_probability * 100)}%`);
  }
  const tooltip = escapeHtml(reasonParts.filter(Boolean).join(" "));
  const caution = p.trust_fake_review_probability != null && p.trust_fake_review_probability >= 0.5;

  return `
    <div class="trust-score-badge" title="${tooltip}">
      <div class="trust-score-ring" style="--pct:${score}; --trust-color:${color};">
        <div class="trust-score-inner">
          <span class="trust-score-num">${score}</span>
        </div>
      </div>
      <span class="trust-score-label" style="color:${color};">${escapeHtml(confidence)}${caution ? " ⚠" : ""}</span>
    </div>`;
}

function reviewIntelligencePanel(p) {
  const intel = p.review_intelligence || {};

  const loveItems = (intel.what_people_love || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const complaintItems = (intel.common_complaints || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const bestForChips = (intel.best_for || []).map((tag) => `<span class="mini-chip">${escapeHtml(tag)}</span>`).join("");
  const notForItems = (intel.not_recommended_for || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const sourceEntries = Object.entries(intel.source_summaries || {})
    .map(([platform, summary]) => `<div class="source-summary"><strong>${escapeHtml(platform)}:</strong> ${escapeHtml(summary)}</div>`)
    .join("");

  const report = p.decision_report;
  const allReasons = (report && report.reasons) || [];
  const allCautions = (report && report.cautions) || [];
  const reportSection = (allReasons.length || allCautions.length) ? `
    <div class="review-section">
      <h4>✅ Why This Product?</h4>
      ${allReasons.length ? `<ul class="pros-list">${allReasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>` : ""}
      ${allCautions.length ? `<ul class="cons-list">${allCautions.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>` : ""}
    </div>` : "";

  const hasContent = loveItems || complaintItems || bestForChips || notForItems || sourceEntries || reportSection;
  if (!hasContent) return "";

  const reliability = intel.long_term_reliability || "Unknown";
  const warranty = intel.warranty_experience || "Unknown";

  return `
    <button type="button" class="ai-review-toggle">AI Review ▾</button>
    <div class="ai-review-panel" hidden>
      ${reportSection}
      ${loveItems ? `<div class="review-section"><h4>👍 What People Love</h4><ul>${loveItems}</ul></div>` : ""}
      ${complaintItems ? `<div class="review-section"><h4>⚠️ Common Complaints</h4><ul>${complaintItems}</ul></div>` : ""}
      ${bestForChips ? `<div class="review-section"><h4>Best For</h4><div class="chip-mini-row">${bestForChips}</div></div>` : ""}
      ${notForItems ? `<div class="review-section"><h4>Not Recommended For</h4><ul>${notForItems}</ul></div>` : ""}
      ${reliability !== "Unknown" || warranty !== "Unknown" ? `
      <div class="review-section reliability-row">
        <span>Reliability: <strong>${escapeHtml(reliability)}</strong></span>
        <span>Warranty: <strong>${escapeHtml(warranty)}</strong></span>
      </div>` : ""}
      ${intel.disagreement_note ? `<div class="review-section disagreement-note">⚡ ${escapeHtml(intel.disagreement_note)}</div>` : ""}
      ${sourceEntries ? `<div class="review-section"><h4>Sources</h4>${sourceEntries}</div>` : ""}
      <div class="review-confidence">AI Confidence: ${intel.ai_confidence ?? 0}%</div>
    </div>`;
}

function decisionChecklistPreview(p) {
  const report = p.decision_report;
  if (!report) return "";
  const reasons = report.reasons || [];
  const cautions = report.cautions || [];
  if (!reasons.length && !cautions.length) return "";

  const previewReasons = reasons.slice(0, 3).map((r) => `<li>✓ ${escapeHtml(r)}</li>`).join("");
  const moreCount = Math.max(0, reasons.length - 3);
  const cautionBadge = cautions.length
    ? `<div class="checklist-caution-badge">⚠ ${cautions.length} thing${cautions.length > 1 ? "s" : ""} to note</div>`
    : "";

  return `
    <div class="decision-checklist">
      ${previewReasons ? `<ul class="checklist-preview">${previewReasons}</ul>` : ""}
      ${moreCount ? `<div class="checklist-more">+${moreCount} more in AI Review</div>` : ""}
      ${cautionBadge}
    </div>`;
}

const SMART_LABEL_ICONS = {
  "Best Overall": "🏆",
  "Best Budget": "💸",
  "Best Premium": "💎",
  "Best Value": "⚖️",
  "Best Camera": "📷",
  "Best Battery": "🔋",
  "Best Gaming": "🎮",
  "Best Student Choice": "🎓",
  "Best Office Choice": "💼",
  "Best Travel Choice": "✈️",
};

function smartLabelsRow(p) {
  const labels = p.smart_labels || [];
  if (!labels.length) return "";
  const chips = labels.map((label) => {
    const icon = SMART_LABEL_ICONS[label] || "⭐";
    return `<span class="smart-label-chip">${icon} ${escapeHtml(label)}</span>`;
  }).join("");
  return `<div class="smart-labels-row">${chips}</div>`;
}

function priceDealColor(recommendation) {
  if (recommendation === "Excellent Deal") return "var(--success)";
  if (recommendation === "Buy Now") return "var(--primary)";
  if (recommendation === "Poor Deal") return "var(--danger)";
  return "var(--warning)"; // Wait
}

function priceIntelligenceBadge(p) {
  const intel = p.price_intelligence;
  if (!intel || !intel.recommendation || intel.recommendation === "Unknown") return "";

  const color = priceDealColor(intel.recommendation);
  const tooltip = escapeHtml(intel.reason || "");

  return `<div class="deal-badge" style="--deal-color:${color};" title="${tooltip}">${escapeHtml(intel.recommendation)}</div>`;
}

function priceIntelligenceDetail(p) {
  const intel = p.price_intelligence;
  if (!intel || intel.average_price == null) return "";
  const fmt = (n) => `₹${Math.round(n).toLocaleString("en-IN")}`;
  return `<div class="price-context">Today's avg ${fmt(intel.average_price)} · low ${fmt(intel.lowest_price)} · high ${fmt(intel.highest_price)}</div>`;
}

function sellerTrustLine(p) {
  const seller = p.seller_intelligence;
  const storeName = escapeHtml(p.source) || "";
  if (!seller) return `<div class="store">${storeName}</div>`;

  const pct = seller.seller_trust_percent;
  const color = pct >= 75 ? "var(--success)" : pct >= 50 ? "var(--warning)" : "var(--danger)";
  const tooltip = escapeHtml(seller.reason || "");

  return `
    <div class="store seller-trust-row" title="${tooltip}">
      <span>${storeName}</span>
      <span class="seller-trust-chip" style="--seller-color:${color};">${escapeHtml(seller.seller_category)} · ${pct}%</span>
    </div>`;
}

function productKey(p) {
  return String(p.product_id || p.title || "");
}

function productCard(p) {
  const link = p.product_link || p.link || "#";
  const features = (p.features && p.features.join(", ")) || "";
  const sourcesCount = p.review_sources_count;
  const platformCounts = p.review_platform_counts || {};
  const platformsLabel = Object.entries(platformCounts)
    .map(([platform, count]) => `${platform} (${count})`)
    .join(", ");
  const key = productKey(p);
  const isSelected = compareSelection.has(key);

  return `
    <div class="product-card">
      <label class="compare-checkbox-wrap" title="Select to compare">
        <input type="checkbox" class="compare-checkbox" data-key="${escapeHtml(key)}" ${isSelected ? "checked" : ""}>
        <span>Compare</span>
      </label>
      <div class="img-wrap">
        <img src="${p.thumbnail || ""}" alt="" loading="lazy">
        ${trustScoreBadge(p)}
      </div>
      <div class="card-body">
        ${smartLabelsRow(p)}
        <a class="title" href="${link}" target="_blank" rel="noopener">${escapeHtml(p.title) || "Untitled product"}</a>
        <div class="price-row">
          <span class="price">${escapeHtml(p.price) || "N/A"}</span>
          <span class="rating">★ ${p.rating ?? "N/A"}</span>
        </div>
        ${priceIntelligenceBadge(p)}
        ${priceIntelligenceDetail(p)}
        <div class="reviews">${p.reviews ? `${p.reviews} reviews` : "No reviews yet"}</div>
        ${sellerTrustLine(p)}
        ${features ? `<div class="features">${escapeHtml(features)}</div>` : ""}
        ${sourcesCount != null ? `<div class="badge" title="${escapeHtml(platformsLabel)}">Cross-checked: ${sourcesCount} sources</div>` : ""}
        ${decisionChecklistPreview(p)}
        ${p.why_recommend ? `<div class="features" style="margin-top:2px;">${escapeHtml(p.why_recommend)}</div>` : ""}
        ${reviewIntelligencePanel(p)}
        ${p.extracted_price ? `<button type="button" class="deal-optimizer-btn" data-key="${escapeHtml(key)}">💰 Deal Optimizer</button>` : ""}
        <a class="buy-btn" href="${link}" target="_blank" rel="noopener">View Product</a>
      </div>
    </div>`;
}

function renderAiResult(container, data) {
  const headline = extractHeadline(data.reply) || "Here's what I found:";
  const summaryLines = extractSummaryLines(data.reply);

  let html = `<div class="bubble">${escapeHtml(headline)}</div>`;

  if (data.needs_input) {
    // The AI Buying Advisor (or a clarification question) is asking the
    // user something — the reply bubble above already shows the question.
    // There's nothing to search for yet, so don't show a "no results"
    // state card underneath it; that reads as an error when it isn't one.
  } else if (!data.products || data.products.length === 0) {
    html += `
      <div class="state-card">
        <div class="state-icon">🔍</div>
        <div>No perfect matches found. Try changing filters or adjusting your budget.</div>
      </div>`;
  } else {
    if (summaryLines.length) {
      html += `<div class="summary-strip">`;
      summaryLines.forEach((line) => {
        const [label, ...rest] = line.split(":");
        html += `<div class="row"><span class="label">${escapeHtml(label)}:</span>${escapeHtml(rest.join(":").trim())}</div>`;
      });
      html += `</div>`;
    }
    data.products.forEach((p) => productLookup.set(productKey(p), p));
    html += `<div class="product-grid">${data.products.map(productCard).join("")}</div>`;
  }

  container.innerHTML = html;
}

// ---------- Product Comparison (Module 7) ----------
const compareBar = document.getElementById("compareBar");
const compareCount = document.getElementById("compareCount");
const compareClearBtn = document.getElementById("compareClearBtn");
const compareGoBtn = document.getElementById("compareGoBtn");
const compareModalOverlay = document.getElementById("compareModalOverlay");
const compareModalBody = document.getElementById("compareModalBody");
const compareModalClose = document.getElementById("compareModalClose");

function updateCompareBar() {
  const n = compareSelection.size;
  if (n === 0) {
    compareBar.hidden = true;
    return;
  }
  compareBar.hidden = false;
  compareCount.textContent = `${n} selected${n > MAX_COMPARE ? ` (max ${MAX_COMPARE})` : ""}`;
  compareGoBtn.disabled = n < 2 || n > MAX_COMPARE;
  compareGoBtn.style.opacity = compareGoBtn.disabled ? "0.5" : "1";
}

chatArea.addEventListener("change", (e) => {
  const checkbox = e.target.closest(".compare-checkbox");
  if (!checkbox) return;

  const key = checkbox.dataset.key;
  if (checkbox.checked) {
    if (compareSelection.size >= MAX_COMPARE) {
      checkbox.checked = false;
      return;
    }
    const product = productLookup.get(key);
    if (product) compareSelection.set(key, product);
  } else {
    compareSelection.delete(key);
  }
  updateCompareBar();
});

compareClearBtn.addEventListener("click", () => {
  compareSelection.clear();
  document.querySelectorAll(".compare-checkbox:checked").forEach((cb) => (cb.checked = false));
  updateCompareBar();
});

function compareTableHtml(result) {
  const titles = Object.keys(result.axes[0]?.values || {});
  const headerCells = titles.map((t) => `<th>${escapeHtml(t)}</th>`).join("");
  const rows = result.axes.map((axis) => {
    const cells = titles.map((t) => {
      const isWinnerCol = t === result.winner;
      const value = axis.values[t] ?? "N/A";
      return `<td class="${isWinnerCol ? "winner-cell" : ""}">${escapeHtml(value)}</td>`;
    }).join("");
    return `<tr><th>${escapeHtml(axis.axis)}</th>${cells}</tr>`;
  }).join("");

  return `
    <div class="compare-table-wrap">
      <table class="compare-table">
        <thead><tr><th></th>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function comparePresConsHtml(result) {
  const blocks = Object.entries(result.per_product_pros_cons || {}).map(([title, pc]) => {
    const pros = (pc.pros || []).map((p) => `<li>${escapeHtml(p)}</li>`).join("");
    const cons = (pc.cons || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("");
    return `
      <div class="compare-product-block">
        <h4>${escapeHtml(title)}</h4>
        ${pros ? `<ul class="pros-list">${pros}</ul>` : ""}
        ${cons ? `<ul class="cons-list">${cons}</ul>` : ""}
      </div>`;
  }).join("");

  return blocks ? `<div class="compare-pros-cons-grid">${blocks}</div>` : "";
}

function openCompareModal(result) {
  compareModalBody.innerHTML = `
    <div class="compare-winner-banner">
      <div class="label">🏆 Winner</div>
      <div class="title">${escapeHtml(result.winner)}</div>
      <div class="verdict">${escapeHtml(result.verdict)}</div>
    </div>
    ${compareTableHtml(result)}
    ${comparePresConsHtml(result)}
  `;
  compareModalOverlay.hidden = false;
}

compareModalClose.addEventListener("click", () => (compareModalOverlay.hidden = true));
compareModalOverlay.addEventListener("click", (e) => {
  if (e.target === compareModalOverlay) compareModalOverlay.hidden = true;
});

compareGoBtn.addEventListener("click", async () => {
  if (compareSelection.size < 2) return;
  const products = Array.from(compareSelection.values());

  compareGoBtn.disabled = true;
  compareGoBtn.textContent = "Comparing...";
  try {
    const res = await fetch("/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ products }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Unable to compare these products right now.");
      return;
    }
    openCompareModal(data);
  } catch (err) {
    alert("Unable to compare these products right now. Check your connection and try again.");
  } finally {
    compareGoBtn.disabled = false;
    compareGoBtn.textContent = "Compare";
  }
});

// ---------- Deal Optimizer (Module 8) ----------
// A savings CALCULATOR, not an offer-discovery tool — the user enters real
// offers they've actually found (a coupon, a card discount, an exchange
// value); nothing here is fabricated. Pure client<->server arithmetic, no
// AI/search cost.
const dealModalOverlay = document.getElementById("dealModalOverlay");
const dealModalBody = document.getElementById("dealModalBody");
const dealModalClose = document.getElementById("dealModalClose");

const OFFER_TYPE_LABELS = {
  coupon: "Coupon",
  card_offer: "Card Offer",
  exchange: "Exchange",
  cashback: "Cashback",
  student_discount: "Student Discount",
  festival_offer: "Festival Offer",
  upi_offer: "UPI Offer",
  other: "Other",
};

let dealOfferRowId = 0;

function offerRowHtml(id) {
  const options = Object.entries(OFFER_TYPE_LABELS)
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  return `
    <div class="offer-row" data-row-id="${id}">
      <select class="offer-type">${options}</select>
      <input type="number" class="offer-value" placeholder="Amount" min="0" step="1">
      <select class="offer-is-percent">
        <option value="0">₹</option>
        <option value="1">%</option>
      </select>
      <button type="button" class="offer-remove-btn" data-row-id="${id}" title="Remove">✕</button>
    </div>`;
}

function dealModalHtml(product) {
  const price = product.extracted_price;
  dealOfferRowId = 0;
  const firstRowId = dealOfferRowId++;
  return `
    <h3 style="margin:0 0 4px;">💰 Deal Optimizer</h3>
    <div class="deal-price-row">${escapeHtml(product.title)}<br>Listed price: <strong>₹${price.toLocaleString("en-IN")}</strong></div>
    <div id="offerRows">${offerRowHtml(firstRowId)}</div>
    <button type="button" class="deal-add-offer-btn" id="dealAddOfferBtn">+ Add another offer</button>
    <button type="button" class="btn btn-primary btn-block" id="dealCalculateBtn">Calculate Final Price</button>
    <div id="dealResultArea"></div>
  `;
}

function dealResultHtml(result) {
  const offersLines = result.offers_applied.map(
    (o) => `<div class="deal-result-row"><span>${escapeHtml(o.label)}</span><span>−₹${o.amount.toLocaleString("en-IN")}</span></div>`
  ).join("");
  return `
    <div class="deal-result">
      <div class="deal-result-row"><span>Listed price</span><span>₹${result.base_price.toLocaleString("en-IN")}</span></div>
      ${offersLines}
      <div class="deal-result-row"><span>Total savings</span><span>−₹${result.total_savings.toLocaleString("en-IN")} (${result.savings_percent}%)</span></div>
      <div class="deal-result-row final"><span>Final price</span><span>₹${result.final_price.toLocaleString("en-IN")}</span></div>
    </div>`;
}

function openDealModal(product) {
  dealModalBody.innerHTML = dealModalHtml(product);
  dealModalOverlay.hidden = false;
}

dealModalClose.addEventListener("click", () => (dealModalOverlay.hidden = true));
dealModalOverlay.addEventListener("click", (e) => {
  if (e.target === dealModalOverlay) dealModalOverlay.hidden = true;
});

chatArea.addEventListener("click", (e) => {
  const btn = e.target.closest(".deal-optimizer-btn");
  if (!btn) return;
  const product = productLookup.get(btn.dataset.key);
  if (product) openDealModal(product);
});

dealModalBody.addEventListener("click", async (e) => {
  if (e.target.id === "dealAddOfferBtn") {
    const id = dealOfferRowId++;
    document.getElementById("offerRows").insertAdjacentHTML("beforeend", offerRowHtml(id));
    return;
  }

  const removeBtn = e.target.closest(".offer-remove-btn");
  if (removeBtn) {
    const row = dealModalBody.querySelector(`.offer-row[data-row-id="${removeBtn.dataset.rowId}"]`);
    if (row && document.querySelectorAll("#offerRows .offer-row").length > 1) row.remove();
    return;
  }

  if (e.target.id === "dealCalculateBtn") {
    const price = parseFloat(dealModalBody.querySelector(".deal-price-row strong").textContent.replace(/[₹,]/g, ""));
    const offers = Array.from(dealModalBody.querySelectorAll(".offer-row")).map((row) => ({
      type: row.querySelector(".offer-type").value,
      value: parseFloat(row.querySelector(".offer-value").value) || 0,
      is_percent: row.querySelector(".offer-is-percent").value === "1",
    })).filter((o) => o.value > 0);

    e.target.disabled = true;
    e.target.textContent = "Calculating...";
    try {
      const res = await fetch("/calculate-deal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_price: price, offers }),
      });
      const data = await res.json();
      const resultArea = document.getElementById("dealResultArea");
      if (!res.ok) {
        resultArea.innerHTML = `<p class="error" style="margin-top:10px;">${escapeHtml(data.error || "Calculation failed.")}</p>`;
      } else {
        resultArea.innerHTML = dealResultHtml(data);
      }
    } catch (err) {
      document.getElementById("dealResultArea").innerHTML = `<p class="error" style="margin-top:10px;">Unable to calculate right now.</p>`;
    } finally {
      e.target.disabled = false;
      e.target.textContent = "Calculate Final Price";
    }
  }
});

function renderAiError(container, message) {
  container.innerHTML = `
    <div class="state-card error">
      <div class="state-icon">⚠️</div>
      <div>${escapeHtml(message)}</div>
    </div>`;
}

async function runSearch(query) {
  appendUserMessage(query);
  saveRecentSearch(query);
  queryInput.value = "";

  const typingMsg = appendTypingMessage();

  const budget = Number(budgetRange.value);
  const payload = { query };
  if (budget > 0) payload.budget_max = budget;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    const msgContent = typingMsg.querySelector(".msg-content");
    const bubble = typingMsg.querySelector(".bubble");
    bubble.outerHTML = skeletonGrid(4);

    await new Promise((r) => setTimeout(r, 250));

    if (!res.ok) {
      renderAiError(msgContent, data.error || "Unable to fetch products. Try again.");
      return;
    }

    renderAiResult(msgContent, data);
    const ts = document.createElement("div");
    ts.className = "timestamp";
    ts.textContent = formatTime();
    msgContent.appendChild(ts);
  } catch (err) {
    const msgContent = typingMsg.querySelector(".msg-content");
    renderAiError(msgContent, "Unable to fetch products. Check your connection and try again.");
  } finally {
    typingMsg.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;
  runSearch(query);
});

chatArea.addEventListener("click", (e) => {
  const toggle = e.target.closest(".ai-review-toggle");
  if (!toggle) return;
  const panel = toggle.nextElementSibling;
  if (!panel) return;
  const isHidden = panel.hasAttribute("hidden");
  if (isHidden) {
    panel.removeAttribute("hidden");
    toggle.textContent = "AI Review ▴";
  } else {
    panel.setAttribute("hidden", "");
    toggle.textContent = "AI Review ▾";
  }
});

document.getElementById("categoryChips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll("#categoryChips .chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  runSearch(chip.dataset.query);
});

recentSearchesEl.addEventListener("click", (e) => {
  const tag = e.target.closest(".tag");
  if (!tag) return;
  runSearch(tag.dataset.query);
});

budgetRange.addEventListener("input", () => {
  const value = Number(budgetRange.value);
  budgetValue.textContent = value > 0 ? `₹${value.toLocaleString("en-IN")}` : "Any";
});

avatarBtn.addEventListener("click", () => {
  avatarMenu.style.display = avatarMenu.style.display === "block" ? "none" : "block";
});
document.addEventListener("click", (e) => {
  if (!avatarBtn.contains(e.target) && !avatarMenu.contains(e.target)) {
    avatarMenu.style.display = "none";
  }
});

if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.lang = "en-IN";
  recognition.interimResults = false;

  micBtn.addEventListener("click", () => {
    micBtn.classList.add("listening");
    recognition.start();
  });
  recognition.addEventListener("result", (e) => {
    queryInput.value = e.results[0][0].transcript;
  });
  recognition.addEventListener("end", () => micBtn.classList.remove("listening"));
  recognition.addEventListener("error", () => micBtn.classList.remove("listening"));
} else {
  micBtn.style.display = "none";
}

renderRecentSearches();

const welcomeMessageEl = document.getElementById("welcomeMessageData");
if (welcomeMessageEl && welcomeMessageEl.dataset.message) {
  appendAiMessage(welcomeMessageEl.dataset.message);
}
