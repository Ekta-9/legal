const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const dropzone = document.getElementById("dropzone");
const textInput = document.getElementById("text-input");
const filePanel = document.getElementById("file-panel");
const textPanel = document.getElementById("text-panel");
const langSelect = document.getElementById("lang-select");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");

function selectedSource() {
  return form.querySelector('input[name="source"]:checked').value;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("is-error", isError);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showSelectedFile() {
  const file = fileInput.files[0];
  fileNameEl.textContent = file ? `${file.name} / ${formatSize(file.size)}` : "";
}

// Only the visible input is ever submitted, so a stale file can't silently win over pasted text.
for (const radio of form.querySelectorAll('input[name="source"]')) {
  radio.addEventListener("change", () => {
    const isFile = selectedSource() === "file";
    filePanel.hidden = !isFile;
    textPanel.hidden = isFile;
    setStatus("");
    (isFile ? fileInput : textInput).focus();
  });
}

fileInput.addEventListener("change", () => {
  showSelectedFile();
  setStatus("");
});

for (const type of ["dragenter", "dragover"]) {
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragover");
  });
}

for (const type of ["dragleave", "drop"]) {
  dropzone.addEventListener(type, () => dropzone.classList.remove("is-dragover"));
}

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  if (event.dataTransfer.files.length > 0) {
    fileInput.files = event.dataTransfer.files;
    showSelectedFile();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData();
  if (selectedSource() === "file") {
    if (fileInput.files.length === 0) {
      setStatus("Choose a file first.", true);
      return;
    }
    formData.append("file", fileInput.files[0]);
  } else {
    if (!textInput.value.trim()) {
      setStatus("Paste some text first.", true);
      return;
    }
    formData.append("text", textInput.value.trim());
  }

  submitBtn.disabled = true;
  setStatus("Uploading...");

  try {
    const response = await fetch("/api/documents", { method: "POST", body: formData });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `upload failed (${response.status})`);
    }
    const { job_id: jobId } = await response.json();
    const lang = encodeURIComponent(langSelect.value);
    window.location.href = `/result.html?job=${encodeURIComponent(jobId)}&lang=${lang}`;
  } catch (err) {
    const message = err instanceof TypeError ? "Can't reach the server. Is it running?" : err.message;
    setStatus(`Error: ${message}`, true);
    submitBtn.disabled = false;
  }
});
