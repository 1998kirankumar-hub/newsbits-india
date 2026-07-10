const NEWS_URL = "news.json";
const REFRESH_MS = 5 * 60 * 1000; // re-check for fresh news every 5 minutes

let newsData = null;
let activeCategory = "Top Stories";

const listEl = document.getElementById("news-list");
const statusEl = document.getElementById("status-msg");
const tabsEl = document.getElementById("tabs");
const lastUpdatedEl = document.getElementById("last-updated");

function timeAgo(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffMin = Math.round((now - then) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

function renderTabs(categories) {
  tabsEl.innerHTML = "";
  Object.keys(categories).forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (cat === activeCategory ? " active" : "");
    btn.textContent = cat;
    btn.addEventListener("click", () => {
      activeCategory = cat;
      renderTabs(categories);
      renderList();
    });
    tabsEl.appendChild(btn);
  });
}

function renderList() {
  if (!newsData) return;
  const items = newsData.categories[activeCategory] || [];
  listEl.innerHTML = "";

  if (items.length === 0) {
    statusEl.textContent = "No stories in this category yet. Check back soon.";
    statusEl.style.display = "block";
    return;
  }
  statusEl.style.display = "none";

  items.forEach((item, idx) => {
    const li = document.createElement("li");

    const body = document.createElement("div");
    body.className = "item-body";

    const a = document.createElement("a");
    a.className = "headline";
    a.href = item.link;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = item.title;

    const meta = document.createElement("div");
    meta.className = "item-meta";
    const sourceTag = document.createElement("span");
    sourceTag.className = "source-tag";
    sourceTag.textContent = item.source || "";
    meta.appendChild(sourceTag);
    meta.appendChild(document.createTextNode(timeAgo(item.published)));

    body.appendChild(a);
    body.appendChild(meta);

    if (item.summary) {
      const summary = document.createElement("p");
      summary.className = "item-summary";
      summary.textContent = item.summary;
      body.appendChild(summary);
    }

    const continueLink = document.createElement("a");
    continueLink.className = "continue-link";
    continueLink.href = item.link;
    continueLink.target = "_blank";
    continueLink.rel = "noopener noreferrer";
    continueLink.textContent = `Continue reading on ${item.source || "source"} →`;
    body.appendChild(continueLink);

    li.appendChild(body);
    listEl.appendChild(li);

    // Drop an in-feed ad slot after the 6th headline in the active list
    if (idx === 5 && items.length > 6) {
      const adLi = document.createElement("li");
      adLi.className = "ad-item";
      adLi.style.display = "block";
      adLi.style.border = "none";
      adLi.style.padding = "0";
      adLi.innerHTML = `<div class="ad-slot" id="ad-infeed">Ad slot &mdash; paste your AdSense in-feed ad unit code here</div>`;
      listEl.appendChild(adLi);
    }
  });
}

async function loadNews() {
  try {
    const res = await fetch(`${NEWS_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    newsData = data;
    lastUpdatedEl.textContent = `Updated ${timeAgo(data.updated_at)}`;
    renderTabs(data.categories);
    renderList();
  } catch (err) {
    statusEl.textContent = "Couldn't load the news feed. Run fetch_news.py or check back shortly.";
    statusEl.style.display = "block";
    console.error(err);
  }
}

function initTheme() {
  const saved = localStorage.getItem("theme");
  const theme = saved || "light";
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("theme-toggle").textContent = theme === "dark" ? "Light mode" : "Dark mode";
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  document.getElementById("theme-toggle").textContent = next === "dark" ? "Light mode" : "Dark mode";
}

document.getElementById("theme-toggle").addEventListener("click", toggleTheme);

initTheme();
loadNews();
setInterval(loadNews, REFRESH_MS);
