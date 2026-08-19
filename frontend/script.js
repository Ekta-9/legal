const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const textInput = document.getElementById("text-input");
const langSelect = document.getElementById("lang-select");
const statusEl = document.getElementById("status");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
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
  const lang = encodeURIComponent(langSelect.value);
  window.location.href = `/result.html?job=${jobId}&lang=${lang}`;
});
