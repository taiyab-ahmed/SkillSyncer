const $ = id => document.getElementById(id);
const form = $("candidate-form"), submitBtn = $("submit-btn"), resumeInput = $("resume"), fileNameEl = $("file-name");
const MAX_BYTES = 4 * 1024 * 1024;

function setState(state) {
  $("output-empty").hidden = state !== "empty";
  $("output-loading").hidden = state !== "loading";
  $("result").hidden = state !== "result";
}
function escapeHTML(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function renderError(messages) {
  setState("empty");
  const box = $("output-empty");
  box.innerHTML = '<div class="error-box"><strong>Please fix the following:</strong><ul>' +
    messages.map(m => `<li>${escapeHTML(m)}</li>`).join("") + "</ul></div>";
  box.hidden = false;
}
function checkRow(c) {
  const li = document.createElement("li");
  const mark = document.createElement("span");
  mark.className = "mark " + (c.ok ? "yes" : "no");
  mark.textContent = c.ok ? "✓" : "✕";
  const text = document.createElement("span");
  const label = document.createElement("span"); label.className = "check__label"; label.textContent = c.label;
  const detail = document.createElement("span"); detail.className = "check__detail"; detail.textContent = c.detail;
  text.append(label, detail);
  li.append(mark, text);
  return li;
}
function renderResult(data) {
  const pass = data.result === "MATCHING";
  $("result-band").className = "result__band " + (pass ? "pass" : "fail");
  $("result-status").textContent = pass ? "Matching" : "Not matching";
  $("result-sub").textContent = data.role + " · " + data.resume;
  const list = $("result-checklist");
  list.innerHTML = "";
  data.checks.forEach(c => list.appendChild(checkRow(c)));
  const chips = $("extracted-skills");
  chips.innerHTML = "";
  if (!data.skills.length) { chips.textContent = "None detected"; chips.className = "chips muted"; }
  else {
    chips.className = "chips";
    data.skills.forEach(s => { const el = document.createElement("span"); el.className = "chip"; el.textContent = s; chips.appendChild(el); });
  }
  $("result-reasons").innerHTML = pass ? "" :
    "<strong>Why it did not match</strong><ul>" + data.reasons.map(r => `<li>${escapeHTML(r)}</li>`).join("") + "</ul>";
  setState("result");
}
resumeInput.addEventListener("change", () => {
  const file = resumeInput.files[0];
  if (!file) { fileNameEl.textContent = "No file chosen · PDF, max 4 MB"; return; }
  if (!file.name.toLowerCase().endsWith(".pdf")) { alert("Please choose a PDF file."); resumeInput.value = ""; fileNameEl.textContent = "No file chosen"; return; }
  if (file.size > MAX_BYTES) { alert("PDF must be 4 MB or smaller."); resumeInput.value = ""; fileNameEl.textContent = "No file chosen"; return; }
  fileNameEl.textContent = file.name;
});
const dropZone = $("drop-zone");
["dragenter", "dragover"].forEach(t => dropZone.addEventListener(t, () => dropZone.classList.add("dragging")));
["dragleave", "drop"].forEach(t => dropZone.addEventListener(t, () => dropZone.classList.remove("dragging")));
dropZone.addEventListener("drop", e => {
  if (e.dataTransfer.files.length) { resumeInput.files = e.dataTransfer.files; resumeInput.dispatchEvent(new Event("change")); }
});
form.addEventListener("submit", async e => {
  e.preventDefault();
  submitBtn.disabled = true; submitBtn.textContent = "Analyzing…"; setState("loading");
  try {
    const res = await fetch("/analyze", {method: "POST", body: new FormData(form)});
    const data = await res.json();
    if (!res.ok || data.error) renderError(data.messages || ["Something went wrong."]);
    else renderResult(data);
  } catch (err) {
    renderError(["Could not reach the app. Check that python app.py is running."]);
  } finally { submitBtn.disabled = false; submitBtn.textContent = "Analyze resume"; }
});
const themeToggle = $("theme-toggle");
themeToggle.addEventListener("click", () => {
  document.body.classList.toggle("dark-mode");
  themeToggle.textContent = document.body.classList.contains("dark-mode") ? "Light mode" : "Dark mode";
});