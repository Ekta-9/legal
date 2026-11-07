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

const docTypeSelect = document.getElementById("doc-type-select");
const docTypeOther = document.getElementById("doc-type-other");
const roleSelect = document.getElementById("role-select");
const roleOther = document.getElementById("role-other");

const OTHER = "__other__";
// document type -> the sides a reader can be on; "Other" is added to both lists
const DOCUMENT_TYPES = {
  "Rental / lease agreement": ["Tenant", "Landlord / owner"],
  "Leave and licence agreement": ["Licensee (the one staying)", "Licensor (the owner)"],
  "Shop or commercial lease": ["Shopkeeper / tenant", "Property owner"],
  "Employment contract / offer letter": ["Employee", "Employer"],
  "Freelance or service agreement": ["Service provider / freelancer", "Client"],
  "Non-disclosure agreement (NDA)": ["Receiving the information", "Sharing the information", "Both sides (mutual NDA)"],
  "Loan agreement": ["Borrower", "Lender", "Guarantor"],
  "Sale agreement (property or goods)": ["Buyer", "Seller"],
  "Partnership deed": ["Partner"],
  "Terms of service / app agreement": ["User / customer", "Company / provider"],
};

function addOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
}

for (const type of Object.keys(DOCUMENT_TYPES)) addOption(docTypeSelect, type, type);
addOption(docTypeSelect, OTHER, "Other");

function showOther(select, input) {
  input.hidden = select.value !== OTHER;
  if (!input.hidden) input.focus();
}

function fillRoles() {
  const type = docTypeSelect.value;
  roleSelect.replaceChildren();
  if (!type) {
    addOption(roleSelect, "", "Choose the document type first");
    roleSelect.disabled = true;
  } else {
    addOption(roleSelect, "", "Not specified");
    for (const role of DOCUMENT_TYPES[type] || []) addOption(roleSelect, role, role);
    addOption(roleSelect, OTHER, "Other");
    roleSelect.disabled = false;
  }
  roleOther.hidden = true;
  roleOther.value = "";
}

docTypeSelect.addEventListener("change", () => {
  fillRoles();
  showOther(docTypeSelect, docTypeOther);
});
roleSelect.addEventListener("change", () => showOther(roleSelect, roleOther));

// the chosen option, or what was typed under "Other"
function pickedValue(select, input) {
  return select.value === OTHER ? input.value.trim() : select.value;
}

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
  const documentType = pickedValue(docTypeSelect, docTypeOther);
  const role = pickedValue(roleSelect, roleOther);
  if (documentType) formData.append("document_type", documentType);
  if (role) formData.append("role", role);

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
