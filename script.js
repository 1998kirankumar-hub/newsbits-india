const NEWS_URL = "news.json";
const REFRESH_MS = 5 * 60 * 1000; // re-check for fresh news every 5 minutes

// Fixed display order for the language tab bar (news.json may not list
// them in this order, and may not include all of them if a fetch run
// failed for a given language — we only render tabs for languages that
// are actually present in the data).
const LANGUAGE_ORDER = ["en", "hi", "gu", "ta", "te", "kn", "bn"];

// Gives each category its own voice instead of a generic "Top Stories" list.
// tagline = shown under the tabs for the active category.
// badge = shown on the lead story in that category.
// Keyed by the category name as it appears in news.json (English internal
// names are used for all languages; label translations for the tab text
// itself live in CATEGORY_LABELS below).
const CATEGORY_INFO = {
  "Top Stories": { tagline: "What's blowing up right now, across everything.", badge: "🔥 Trending Now" },
  "India": { tagline: "What's happening back home.", badge: "📍 Must Read" },
  "World": { tagline: "The world, in a nutshell.", badge: "🌍 Big Story" },
  "Business": { tagline: "Follow the money.", badge: "💰 Market Alert" },
  "Sports": { tagline: "Score, drama, repeat.", badge: "🏆 Game Alert" },
  "Technology": { tagline: "What's new, what's next.", badge: "⚡ Just Dropped" },
  "Entertainment": { tagline: "Off-duty reading.", badge: "🎬 Buzzing" },
};

// Native-script tab labels per language for the (few) category names that
// appear outside English. Falls back to the plain English category name
// if a language/category combination isn't listed here.
const CATEGORY_LABELS = {
  "Top Stories": { hi: "मुख्य समाचार", gu: "મુખ્ય સમાચાર", ta: "முதன்மை செய்திகள்", te: "ప్రధాన వార్తలు", kn: "ಪ್ರಮುಖ ಸುದ್ದಿ", bn: "প্রধান খবর" },
  "Entertainment": { hi: "मनोरंजन", gu: "મનોરંજન", ta: "பொழுதுபோக்கு", te: "వినోదం", kn: "ಮನರಂಜನೆ", bn: "বিনোদন" },
};

let newsData = null;
let activeLanguage = "en";
let activeCategory = "Top Stories";

const listEl = document.getElementById("news-list");
const statusEl = document.getElementById("status-msg");
const langTabsEl = document.getElementById("lang-tabs");
const tabsEl = document.getElementById("tabs");
const lastUpdatedEl = document.getElementById("last-updated");
const taglineEl = document.getElementById("category-tagline");

function categoryLabel(cat, lang) {
  return (CATEGORY_LABELS[cat] || {})[lang] || cat;
}

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

function renderLangTabs(languages) {
  langTabsEl.innerHTML = "";
  const codes = LANGUAGE_ORDER.filter((code) => languages[code]);
  codes.forEach((code) => {
    const btn = document.createElement("button");
    btn.className = "tab-btn lang-tab-btn" + (code === activeLanguage ? " active" : "");
    btn.textContent = languages[code].label || code;
    btn.lang = code;
    btn.addEventListener("click", () => {
      if (activeLanguage === code) return;
      activeLanguage = code;
      // Reset to this language's first category (usually "Top Stories")
      const cats = Object.keys(newsData.languages[activeLanguage].categories);
      activeCategory = cats.includes("Top Stories") ? "Top Stories" : cats[0];
      renderLangTabs(languages);
      renderCategoryTabs();
      renderList();
    });
    langTabsEl.appendChild(btn);
  });
}

function renderCategoryTabs() {
  const categories = newsData.languages[activeLanguage].categories;
  tabsEl.innerHTML = "";
  Object.keys(categories).forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (cat === activeCategory ? " active" : "");
    btn.textContent = categoryLabel(cat, activeLanguage);
    btn.lang = activeLanguage;
    btn.addEventListener("click", () => {
      activeCategory = cat;
      renderCategoryTabs();
      renderList();
    });
    tabsEl.appendChild(btn);
  });
  if (taglineEl) {
    taglineEl.textContent = (CATEGORY_INFO[activeCategory] || {}).tagline || "";
  }
}

function renderList() {
  if (!newsData) return;
  const categories = newsData.languages[activeLanguage].categories;
  const items = categories[activeCategory] || [];
  listEl.innerHTML = "";
  listEl.lang = activeLanguage;

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

    if (idx === 0) {
      const badge = document.createElement("span");
      badge.className = "top-badge";
      badge.textContent = (CATEGORY_INFO[activeCategory] || {}).badge || "🔥 Top Pick";
      body.appendChild(badge);
    }

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

    // If the previously active language/category no longer exists in the
    // fresh data (e.g. first load), fall back to sane defaults.
    if (!newsData.languages[activeLanguage]) {
      activeLanguage = LANGUAGE_ORDER.find((c) => newsData.languages[c]) || Object.keys(newsData.languages)[0];
    }
    const cats = Object.keys(newsData.languages[activeLanguage].categories);
    if (!cats.includes(activeCategory)) {
      activeCategory = cats.includes("Top Stories") ? "Top Stories" : cats[0];
    }

    lastUpdatedEl.textContent = `Updated ${timeAgo(data.updated_at)}`;
    renderLangTabs(data.languages);
    renderCategoryTabs();
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
