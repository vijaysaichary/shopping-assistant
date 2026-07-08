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

function productCard(p) {
  const link = p.product_link || p.link || "#";
  const features = (p.features && p.features.join(", ")) || "";
  const sourcesCount = p.review_sources_count;
  const platformCounts = p.review_platform_counts || {};
  const platformsLabel = Object.entries(platformCounts)
    .map(([platform, count]) => `${platform} (${count})`)
    .join(", ");

  return `
    <div class="product-card">
      <div class="img-wrap">
        <img src="${p.thumbnail || ""}" alt="" loading="lazy">
      </div>
      <div class="card-body">
        <a class="title" href="${link}" target="_blank" rel="noopener">${escapeHtml(p.title) || "Untitled product"}</a>
        <div class="price-row">
          <span class="price">${escapeHtml(p.price) || "N/A"}</span>
          <span class="rating">★ ${p.rating ?? "N/A"}</span>
        </div>
        <div class="reviews">${p.reviews ? `${p.reviews} reviews` : "No reviews yet"}</div>
        <div class="store">${escapeHtml(p.source) || ""}</div>
        ${features ? `<div class="features">${escapeHtml(features)}</div>` : ""}
        ${sourcesCount != null ? `<div class="badge" title="${escapeHtml(platformsLabel)}">Cross-checked: ${sourcesCount} sources</div>` : ""}
        ${p.why_recommend ? `<div class="features" style="margin-top:2px;">${escapeHtml(p.why_recommend)}</div>` : ""}
        <a class="buy-btn" href="${link}" target="_blank" rel="noopener">View Product</a>
      </div>
    </div>`;
}

function renderAiResult(container, data) {
  const headline = extractHeadline(data.reply) || "Here's what I found:";
  const summaryLines = extractSummaryLines(data.reply);

  let html = `<div class="bubble">${escapeHtml(headline)}</div>`;

  if (!data.products || data.products.length === 0) {
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
    html += `<div class="product-grid">${data.products.map(productCard).join("")}</div>`;
  }

  container.innerHTML = html;
}

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
