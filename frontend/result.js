const statusEl = document.getElementById("status");
const originalDocEl = document.getElementById("original-doc");
const simplifiedDocEl = document.getElementById("simplified-doc");
const simplifiedHeadingEl = document.getElementById("simplified-heading");
const downloadBtn = document.getElementById("download-btn");

const LANGUAGES = { en: "English", hi: "Hindi", mr: "Marathi" };

const POLL_INTERVAL_MS = 1500;

const params = new URLSearchParams(window.location.search);
const jobId = params.get("job");
const targetLang = params.get("lang") || "en";

let renderedIds = new Set();
let skeletonBuilt = false;
let jobDone = false;
let pendingTranslations = 0;

simplifiedHeadingEl.textContent =
  targetLang === "en" ? "Simplified" : `Simplified (${LANGUAGES[targetLang] || targetLang})`;

downloadBtn.addEventListener("click", () => {
  window.print();
});

if (!jobId) {
  statusEl.textContent = "No document to show — upload one first.";
} else {
  startPolling(jobId);
}

function startPolling(id) {
  poll(id);
  const pollTimer = setInterval(() => {
    poll(id, pollTimer);
  }, POLL_INTERVAL_MS);
}

async function poll(id, timer) {
  const response = await fetch(`/api/documents/${id}`);
  if (!response.ok) {
    statusEl.textContent = "Job not found.";
    if (timer) clearInterval(timer);
    return;
  }

  const data = await response.json();

  if (!skeletonBuilt && data.total_clauses > 0) {
    buildSkeleton(data.total_clauses);
    skeletonBuilt = true;
  }

  for (const clause of data.completed) {
    if (!renderedIds.has(clause.id)) {
      renderedIds.add(clause.id);
      renderClause(clause);
    }
  }
  statusEl.textContent = `${data.status} (${data.completed.length}/${data.total_clauses})`;

  if (data.status === "done" || data.status === "failed") {
    if (timer) clearInterval(timer);
    if (data.status === "failed") {
      statusEl.textContent = `Failed: ${data.error}`;
    } else if (data.total_clauses === 0) {
      originalDocEl.innerHTML = "<p class=\"doc-empty\">No clauses found in this document.</p>";
      simplifiedDocEl.innerHTML = "<p class=\"doc-empty\">Nothing to simplify.</p>";
    }
    jobDone = true;
    maybeEnableDownload();
  }
}

function maybeEnableDownload() {
  downloadBtn.disabled = !(jobDone && pendingTranslations === 0);
}

// clause ids are "clause_<n>" (1-indexed) — see app/parsing/clause_splitter.py
function parseClauseNumber(id) {
  const match = /_(\d+)$/.exec(id);
  return match ? parseInt(match[1], 10) : null;
}

function buildSkeleton(total) {
  for (let n = 1; n <= total; n++) {
    originalDocEl.appendChild(buildSkeletonSlot(`orig-clause-${n}`, n));
    simplifiedDocEl.appendChild(buildSkeletonSlot(`simp-clause-${n}`, n));
  }
}

function buildSkeletonSlot(id, number) {
  const slot = document.createElement("article");
  slot.className = "doc-clause doc-clause--pending";
  slot.id = id;

  const head = document.createElement("div");
  head.className = "doc-clause-head";
  const num = document.createElement("span");
  num.className = "doc-clause-number";
  num.textContent = `${number}.`;
  head.appendChild(num);
  slot.appendChild(head);

  const text = document.createElement("p");
  text.className = "doc-clause-text doc-clause-pending-text";
  text.textContent = "Processing...";
  slot.appendChild(text);

  return slot;
}

function renderClause(clause) {
  const number = parseClauseNumber(clause.id);
  fillOriginalSlot(number, clause);
  fillSimplifiedSlot(number, clause);
}

function fillOriginalSlot(number, clause) {
  const slot = number ? document.getElementById(`orig-clause-${number}`) : null;
  const target = slot || originalDocEl.appendChild(buildSkeletonSlot("", number || "?"));
  target.className = "doc-clause";
  target.innerHTML = "";

  const head = document.createElement("div");
  head.className = "doc-clause-head";
  const num = document.createElement("span");
  num.className = "doc-clause-number";
  num.textContent = `${number || "?"}.`;
  head.appendChild(num);
  if (clause.heading) {
    const heading = document.createElement("span");
    heading.className = "doc-clause-heading";
    heading.textContent = clause.heading;
    head.appendChild(heading);
  }
  target.appendChild(head);

  const text = document.createElement("p");
  text.className = "doc-clause-text";
  text.textContent = clause.original;
  target.appendChild(text);
}

function fillSimplifiedSlot(number, clause) {
  const slot = number ? document.getElementById(`simp-clause-${number}`) : null;
  const target = slot || simplifiedDocEl.appendChild(buildSkeletonSlot("", number || "?"));
  target.className = "doc-clause";
  target.innerHTML = "";

  const head = document.createElement("div");
  head.className = "doc-clause-head";
  const num = document.createElement("span");
  num.className = "doc-clause-number";
  num.textContent = `${number || "?"}.`;
  head.appendChild(num);
  if (clause.heading) {
    const heading = document.createElement("span");
    heading.className = "doc-clause-heading";
    heading.textContent = clause.heading;
    head.appendChild(heading);
  }
  if (clause.self_check) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "⚠ machine-check flagged this — read the original carefully";
    head.appendChild(badge);
  }
  if (clause.readability) {
    head.appendChild(buildReadabilityPill(clause.readability));
  }
  target.appendChild(head);

  const text = document.createElement("p");
  text.className = "doc-clause-text";
  text.textContent = clause.simplified;
  target.appendChild(text);

  if (clause.glossary_matches && clause.glossary_matches.length > 0) {
    target.appendChild(buildGlossaryTerms(clause.glossary_matches));
  }

  if (targetLang !== "en") {
    text.textContent = "Translating...";
    text.classList.add("doc-clause-pending-text");
    pendingTranslations += 1;
    translateClauseText(clause.simplified, targetLang)
      .then((translated) => {
        text.textContent = translated;
        text.classList.remove("doc-clause-pending-text");
        text.classList.add("translate-output");
      })
      .catch((err) => {
        text.textContent = `Translation failed: ${err.message}`;
        text.classList.remove("doc-clause-pending-text");
      })
      .finally(() => {
        pendingTranslations -= 1;
        maybeEnableDownload();
      });
  }
}

async function translateClauseText(text, lang) {
  const response = await fetch("/api/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_lang: lang }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data.translated_text;
}

function buildGlossaryTerms(matches) {
  const wrapper = document.createElement("div");
  wrapper.className = "glossary-terms";

  const label = document.createElement("span");
  label.className = "glossary-label";
  label.textContent = "Related terms:";
  wrapper.appendChild(label);

  for (const match of matches) {
    const term = document.createElement("span");
    term.className = "glossary-term";
    term.textContent = match.term;
    term.title = match.definition; // native tooltip on hover
    wrapper.appendChild(term);
  }

  return wrapper;
}

function buildReadabilityPill(readability) {
  const pill = document.createElement("span");
  const delta = readability.delta;
  pill.className = "readability-pill" + (delta > 0 ? " improved" : delta < 0 ? " worsened" : "");
  const arrow = delta > 0 ? "↓" : delta < 0 ? "↑" : "=";
  pill.textContent = `Grade ${readability.original_grade} ${arrow} ${readability.simplified_grade}`;
  pill.title = `Flesch-Kincaid grade level: ${readability.original_grade} (original) -> ${readability.simplified_grade} (simplified)`;
  return pill;
}
