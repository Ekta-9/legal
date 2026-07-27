const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const textInput = document.getElementById("text-input");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

const POLL_INTERVAL_MS = 1500;
let pollTimer = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  stopPolling();
  resultsEl.innerHTML = "";
  statusEl.textContent = "Uploading...";

  const formData = new FormData();
  if (fileInput.files.length > 0) {
    formData.append("file", fileInput.files[0]);
  } else if (textInput.value.trim()) {
    formData.append("text", textInput.value.trim());
  } else {
    statusEl.textContent = "Provide a file or paste text.";
    return;
  }

  let response;
  try {
    response = await fetch("/api/documents", { method: "POST", body: formData });
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    statusEl.textContent = `Error: ${body.detail || response.statusText}`;
    return;
  }

  const { job_id: jobId } = await response.json();
  statusEl.textContent = "Processing...";
  startPolling(jobId);
});

function startPolling(jobId) {
  const renderedIds = new Set();

  pollTimer = setInterval(async () => {
    const response = await fetch(`/api/documents/${jobId}`);
    if (!response.ok) {
      statusEl.textContent = "Job not found.";
      stopPolling();
      return;
    }

    const data = await response.json();
    for (const clause of data.completed) {
      if (!renderedIds.has(clause.id)) {
        renderedIds.add(clause.id);
        renderClause(clause);
      }
    }
    statusEl.textContent = `${data.status} (${data.completed.length}/${data.total_clauses})`;

    if (data.status === "done" || data.status === "failed") {
      stopPolling();
      if (data.status === "failed") {
        statusEl.textContent = `Failed: ${data.error}`;
      }
    }
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function renderClause(clause) {
  const card = document.createElement("article");
  card.className = "clause-card";

  const heading = document.createElement("div");
  heading.className = "clause-heading";
  heading.textContent = clause.heading || "";
  if (clause.self_check) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "⚠ machine-check flagged this — read the original carefully";
    heading.appendChild(badge);
  }
  if (clause.readability) {
    heading.appendChild(buildReadabilityPill(clause.readability));
  }
  card.appendChild(heading);

  const columns = document.createElement("div");
  columns.className = "clause-columns";
  columns.appendChild(buildColumn("Original", clause.original));
  columns.appendChild(buildColumn("Simplified", clause.simplified));
  card.appendChild(columns);

  resultsEl.appendChild(card);
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

function buildColumn(label, text) {
  const column = document.createElement("div");
  column.className = "clause-column";
  const h = document.createElement("h4");
  h.textContent = label;
  const p = document.createElement("p");
  p.textContent = text;
  column.appendChild(h);
  column.appendChild(p);
  return column;
}
