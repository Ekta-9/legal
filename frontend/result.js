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

const rowsById = new Map();
const renderedIds = new Set();
let failedCount = 0;
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

// The document's own numbering ("§4", "§4.2", "§IV"), "PRE" for the preamble,
// or the position for unnumbered paragraphs — see app/parsing/clause_splitter.py
function clauseLabel(heading, index) {
  if (heading === "Preamble") return "PRE";
  const numbered = /^\s*(\d+(?:\.\d+)*)[.)\s]/.exec(heading || "");
  const article = /^\s*(?:section|article|clause)\s+(\d+(?:\.\d+)*|[IVXLC]+)/i.exec(heading || "");
  const match = numbered || article;
  return match ? `§${match[1]}` : `¶${pad(index + 1)}`;
}

function updateCounter() {
  countDoneEl.textContent = pad(renderedIds.size - failedCount);
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
  const outline = data.clauses || [];
  if (outline.length > 0 && rowsById.size === 0) {
    totalClauses = outline.filter((clause) => !clause.heading_only).length;
    outline.forEach((clause, index) => {
      const row = clause.heading_only ? buildHeadingRow(clause, index) : buildRow(clause, index);
      rowsById.set(clause.id, row);
      clausesEl.appendChild(row);
    });
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
  for (const row of clausesEl.querySelectorAll(".clause.is-pending")) {
    markNotProcessed(row);
  }

  if (data.status === "failed") {
    setStatus(`Failed: ${data.error || "unknown error"}`, true);
  } else if (totalClauses === 0) {
    setStatus("No clauses found in this document.", true);
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Nothing could be split into clauses. Try pasting the text instead.";
    clausesEl.appendChild(empty);
  } else if (failedCount > 0) {
    const labels = [...clausesEl.querySelectorAll(".clause.is-missing")].map((row) => row.dataset.label);
    setStatus(`Done. ${failedCount} clause(s) could not be simplified: ${labels.join(", ")}`, true);
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

function buildRow(clause, index) {
  const label = clauseLabel(clause.heading, index);
  const row = el("article", "clause is-pending");
  row.dataset.label = label;
  row.setAttribute("aria-label", `Clause ${label}`);

  row.appendChild(el("div", "clause-idx", label));

  const original = el("div", "clause-original");
  original.appendChild(el("p", "cell-label mono", "Original"));
  original.appendChild(el("p", "clause-text", clause.text));
  row.appendChild(original);

  const plain = el("div", "clause-plain");
  plain.appendChild(el("p", "cell-label mono", "Plain English"));
  plain.appendChild(el("p", "clause-text", "Processing"));
  plain.appendChild(el("div", "clause-meta mono"));
  plain.appendChild(el("div", "clause-terms"));
  const context = el("div", "clause-terms clause-context");
  fillContext(context, clause.context);
  plain.appendChild(context);
  plain.appendChild(el("div", "translation"));
  row.appendChild(plain);

  return row;
}

// Parties, defined terms and referenced clauses retrieved from elsewhere in the
// same contract (app/rag/document_context.py) — the same material the model was given
function fillContext(container, context) {
  if (!context) return;
  const entries = [];
  for (const party of context.parties || []) {
    const [role, ...rest] = party.split(": ");
    entries.push([role, rest.join(": ")]);
  }
  for (const [term, definition] of Object.entries(context.definitions || {})) {
    entries.push([term, definition.startsWith(`${term}: `) ? definition.slice(term.length + 2) : definition]);
  }
  for (const [number, text] of Object.entries(context.referenced_sections || {})) {
    entries.push([`Clause ${number}`, text]);
  }
  if (entries.length === 0) return;

  container.appendChild(el("span", "terms-label mono", "From this contract"));
  for (const [name, text] of entries) {
    const details = el("details", "term");
    details.appendChild(el("summary", "mono", name));
    details.appendChild(el("p", "", text));
    container.appendChild(details);
  }
}

// A title like "Article 2 Term of Agreement": nothing to simplify, never sent to the model
function buildHeadingRow(clause, index) {
  const label = clauseLabel(clause.heading, index);
  const row = el("div", "clause is-heading");
  row.appendChild(el("div", "clause-idx", label));
  row.appendChild(el("h2", "clause-title", clause.text.replace(/\s+/g, " ")));
  return row;
}

function rowFor(clause) {
  if (!rowsById.has(clause.id)) {
    const row = buildRow({ heading: clause.heading, text: clause.original }, rowsById.size);
    rowsById.set(clause.id, row);
    clausesEl.appendChild(row);
  }
  return rowsById.get(clause.id);
}

function fillRow(clause) {
  const row = rowFor(clause);
  row.classList.remove("is-pending");

  if (clause.failed) {
    failedCount += 1;
    row.classList.add("is-missing");
    row.querySelector(".clause-plain .clause-text").textContent =
      "Not simplified: no usable answer came back for this clause, even after retrying. Read the original carefully.";
    return;
  }

  const plain = row.querySelector(".clause-plain");
  const plainText = plain.querySelector(".clause-text");
  plainText.textContent = clause.simplified;

  if (clause.self_check) {
    plain.insertBefore(el("p", "flag mono", "⚑ Model unsure — read the original closely"), plainText);
  }
  if (clause.missing_numbers && clause.missing_numbers.length > 0) {
    plain.insertBefore(
      el("p", "flag mono", `⚑ Missing from plain version: ${clause.missing_numbers.join(", ")} — check the original`),
      plainText,
    );
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

function markNotProcessed(row) {
  row.classList.remove("is-pending");
  row.classList.add("is-missing");
  row.querySelector(".clause-plain .clause-text").textContent =
    "Not processed: the job stopped before reaching this clause.";
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
