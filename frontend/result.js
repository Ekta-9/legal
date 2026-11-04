const statusEl = document.getElementById("status");
const clausesEl = document.getElementById("clauses");
const countDoneEl = document.getElementById("count-done");
const countTotalEl = document.getElementById("count-total");
const progressBarEl = document.getElementById("progress-bar");
const langLabelEl = document.getElementById("lang-label");
const showOriginalEl = document.getElementById("show-original");
const printBtn = document.getElementById("print-btn");

const LANGUAGES = { en: "English", hi: "Hindi", mr: "Marathi" };
const POLL_INTERVAL_MS = 1500;
const RETRY_INTERVAL_MS = 3000;
const MAX_CONSECUTIVE_ERRORS = 5;

const params = new URLSearchParams(window.location.search);
const jobId = params.get("job");
const targetLang = LANGUAGES[params.get("lang")] ? params.get("lang") : "en";

const renderedIds = new Set();
let totalClauses = 0;
let jobFinished = false;
let consecutiveErrors = 0;

// Translations run one at a time: the server serializes them anyway, and
// firing one request per clause at once is what used to crash it.
const translationQueue = [];
let translating = false;

if (targetLang !== "en") {
  langLabelEl.textContent = `/ + ${LANGUAGES[targetLang]}`;
}

showOriginalEl.addEventListener("change", () => {
  clausesEl.classList.toggle("hide-original", !showOriginalEl.checked);
});

printBtn.addEventListener("click", () => window.print());

if (!jobId) {
  setStatus("No document to show. Upload one first.", true);
} else {
  poll();
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("is-error", isError);
}

function pad(n) {
  return String(n).padStart(2, "0");
}

function clauseNumber(id) {
  // clause ids are "clause_<n>" (1-indexed) — see app/parsing/clause_splitter.py
  const match = /_(\d+)$/.exec(id);
  return match ? parseInt(match[1], 10) : null;
}

function updateCounter() {
  countDoneEl.textContent = pad(renderedIds.size);
  countTotalEl.textContent = pad(totalClauses);
  const pct = totalClauses > 0 ? (renderedIds.size / totalClauses) * 100 : 0;
  progressBarEl.style.width = `${pct}%`;
}

async function poll() {
  let response;
  try {
    response = await fetch(`/api/documents/${encodeURIComponent(jobId)}`);
  } catch {
    consecutiveErrors += 1;
    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
      setStatus("Lost connection to the server. Retrying...", true);
    }
    setTimeout(poll, RETRY_INTERVAL_MS);
    return;
  }
  consecutiveErrors = 0;

  if (response.status === 404) {
    setStatus("This result no longer exists. The server may have restarted. Upload the document again.", true);
    return;
  }
  if (!response.ok) {
    setStatus(`Server error (${response.status}). Retrying...`, true);
    setTimeout(poll, RETRY_INTERVAL_MS);
    return;
  }

  const data = await response.json();
  render(data);

  if (data.status === "done" || data.status === "failed") {
    finish(data);
  } else {
    setTimeout(poll, POLL_INTERVAL_MS);
  }
}

function render(data) {
  if (data.total_clauses > 0 && totalClauses === 0) {
    totalClauses = data.total_clauses;
    for (let n = 1; n <= totalClauses; n++) {
      clausesEl.appendChild(buildRow(n));
    }
  }

  for (const clause of data.completed) {
    if (!renderedIds.has(clause.id)) {
      renderedIds.add(clause.id);
      fillRow(clause);
    }
  }

  updateCounter();
  if (data.status === "pending") {
    setStatus("Queued...");
  } else if (data.status === "processing") {
    setStatus(totalClauses > 0 ? `Simplifying ${renderedIds.size} of ${totalClauses}...` : "Reading document...");
  }
}

function finish(data) {
  jobFinished = true;
  const missing = [];
  for (const row of clausesEl.querySelectorAll(".clause.is-pending")) {
    missing.push(row.dataset.number);
    markMissing(row, data.status === "failed");
  }

  if (data.status === "failed") {
    setStatus(`Failed: ${data.error || "unknown error"}`, true);
  } else if (totalClauses === 0) {
    setStatus("No clauses found in this document.", true);
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Nothing could be split into clauses. Try pasting the text instead.";
    clausesEl.appendChild(empty);
  } else if (missing.length > 0) {
    setStatus(`Done. ${missing.length} clause(s) could not be simplified: §${missing.join(", §")}`, true);
  } else {
    setStatus("Done. All clauses simplified.");
  }
  updatePrintButton();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function buildRow(number) {
  const row = el("article", "clause is-pending");
  row.id = `clause-${number}`;
  row.dataset.number = pad(number);
  row.setAttribute("aria-label", `Clause ${number}`);

  row.appendChild(el("div", "clause-idx", `§${pad(number)}`));

  const original = el("div", "clause-original");
  original.appendChild(el("p", "cell-label mono", "Original"));
  original.appendChild(el("p", "clause-text placeholder", "Waiting..."));
  row.appendChild(original);

  const plain = el("div", "clause-plain");
  plain.appendChild(el("p", "cell-label mono", "Plain English"));
  plain.appendChild(el("p", "clause-text", "Processing"));
  plain.appendChild(el("div", "clause-meta mono"));
  plain.appendChild(el("div", "clause-terms"));
  plain.appendChild(el("div", "translation"));
  row.appendChild(plain);

  return row;
}

function rowFor(clause) {
  const number = clauseNumber(clause.id);
  const existing = number ? document.getElementById(`clause-${number}`) : null;
  if (existing) return existing;
  const row = buildRow(number || renderedIds.size);
  clausesEl.appendChild(row);
  return row;
}

function fillRow(clause) {
  const row = rowFor(clause);
  row.classList.remove("is-pending");

  const originalText = row.querySelector(".clause-original .clause-text");
  originalText.className = "clause-text";
  originalText.textContent = clause.original;

  const plain = row.querySelector(".clause-plain");
  const plainText = plain.querySelector(".clause-text");
  plainText.textContent = clause.simplified;

  if (clause.self_check) {
    plain.insertBefore(el("p", "flag mono", "⚑ Model unsure — read the original closely"), plainText);
  }

  if (clause.readability) {
    plain.querySelector(".clause-meta").appendChild(buildGrade(clause.readability));
  }

  if (clause.glossary_matches && clause.glossary_matches.length > 0) {
    fillTerms(plain.querySelector(".clause-terms"), clause.glossary_matches);
  }

  if (targetLang !== "en") {
    const box = plain.querySelector(".translation");
    box.appendChild(el("p", "translation-label mono", `${LANGUAGES[targetLang]} / experimental machine translation, not reviewed`));
    const text = el("p", "translation-text placeholder", "Queued for translation");
    box.appendChild(text);
    enqueueTranslation(clause.simplified, box, text);
  }
}

function markMissing(row, jobFailed) {
  row.classList.remove("is-pending");
  row.classList.add("is-missing");
  const originalText = row.querySelector(".clause-original .clause-text");
  originalText.textContent = "Not available here. Check this clause in your document.";
  row.querySelector(".clause-plain .clause-text").textContent = jobFailed
    ? "Not processed: the job stopped before reaching this clause."
    : "Not simplified: the model did not return this clause. Read it in your original document.";
}

function buildGrade(readability) {
  const delta = readability.delta;
  const grade = el("span", "grade" + (delta > 0 ? " improved" : delta < 0 ? " worsened" : ""));
  grade.title =
    "Flesch-Kincaid reading grade: roughly the years of schooling needed to read the text. " +
    "It measures sentence and word length only, not whether the meaning is correct.";
  grade.append("Reading grade ");
  grade.appendChild(el("strong", "", `${readability.original_grade} → ${readability.simplified_grade}`));
  return grade;
}

function fillTerms(container, matches) {
  container.appendChild(el("span", "terms-label mono", "Terms"));
  for (const match of matches) {
    const details = el("details", "term");
    details.appendChild(el("summary", "mono", match.term));
    details.appendChild(el("p", "", match.definition));
    container.appendChild(details);
  }
}

function enqueueTranslation(text, box, textEl) {
  translationQueue.push(async () => {
    textEl.textContent = "Translating";
    try {
      textEl.textContent = await translateText(text);
      textEl.classList.remove("placeholder");
    } catch (err) {
      box.classList.add("is-error");
      textEl.classList.remove("placeholder");
      textEl.textContent = `Translation failed (${err.message}). The English version above is unaffected.`;
    }
  });
  pumpTranslations();
}

async function pumpTranslations() {
  if (translating) return;
  translating = true;
  updatePrintButton();
  while (translationQueue.length > 0) {
    await translationQueue.shift()();
  }
  translating = false;
  updatePrintButton();
}

async function translateText(text) {
  let response;
  try {
    response = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, target_lang: targetLang }),
    });
  } catch {
    throw new Error("server unreachable");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `server error ${response.status}`);
  }
  return data.translated_text;
}

function updatePrintButton() {
  printBtn.disabled = !(jobFinished && !translating && translationQueue.length === 0 && renderedIds.size > 0);
}
