// NOBAD Find quick bar. File names and folders are untrusted: they are only ever put in with textContent.
"use strict";
const $ = s => document.querySelector(s);
const KIND = { pdf: "PDF", document: "DOC", spreadsheet: "XLS", slides: "PPT", text: "TXT", code: "</>", email: "MAIL",
  image: "IMG", video: "VID", audio: "AUD", archive: "ZIP", app: "APP", ebook: "BOOK", folder: "DIR", other: "FILE" };
const api = async (name, ...args) => {
  if (!window.pywebview || !pywebview.api || !pywebview.api[name]) return null;
  try { return await pywebview.api[name](...args); } catch (e) { console.warn(name, e); return null; }
};

let rows = [], sel = 0, seq = 0, timer = 0;
const list = $("#list"), q = $("#q"), hint = $("#keys");

function paint(emptyText) {
  list.replaceChildren();
  if (emptyText) {
    const e = document.createElement("li");
    e.className = "empty";
    e.append(document.createTextNode("No match for"));
    const b = document.createElement("b");
    b.textContent = emptyText;
    e.append(b);
    list.append(e);
  }
  rows.forEach((x, i) => {
    const li = document.createElement("li");
    li.className = "row" + (i === sel ? " sel" : "");
    li.id = "r" + i;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", i === sel ? "true" : "false");
    li.dataset.i = i;
    const tag = document.createElement("span"), name = document.createElement("span"), dir = document.createElement("span");
    tag.className = "tag"; tag.textContent = KIND[x.kind] || "FILE";
    name.className = "name"; name.textContent = x.name;
    dir.className = "dir"; dir.textContent = x.folder;
    dir.title = x.folder;
    li.append(tag, name, dir);
    list.append(li);
  });
  hint.hidden = !rows.length;
  q.setAttribute("aria-expanded", rows.length ? "true" : "false");
  q.setAttribute("aria-activedescendant", rows.length ? "r" + sel : "");
  api("fit", rows.length || (emptyText ? 1 : 0));
}

function mark() {
  list.querySelectorAll(".row").forEach((li, i) => {
    li.classList.toggle("sel", i === sel);
    li.setAttribute("aria-selected", i === sel ? "true" : "false");
  });
  q.setAttribute("aria-activedescendant", "r" + sel);
}

async function run() {
  const text = q.value, my = ++seq;
  if (!text.trim()) { rows = []; paint(""); return; }
  const r = await api("search", text);
  if (my !== seq || !r) return;                 // a newer search is already running
  rows = r;
  sel = 0;
  paint(rows.length ? "" : text.trim());
}

function act(how) {
  const x = rows[sel];
  if (how === "to_main") api("to_main", q.value);
  else if (x) api(how, x.id);
}

q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 90); });
list.addEventListener("click", e => { const li = e.target.closest(".row"); if (li) { sel = +li.dataset.i; act(e.ctrlKey ? "reveal" : "open"); } });
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { e.preventDefault(); api("hide"); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (rows.length) { sel = (sel + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length; mark(); }
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    act(e.altKey ? "to_main" : e.ctrlKey ? "reveal" : "open");
  }
});
// Clicking anywhere else (or switching windows) puts the bar away; bar.py ignores the focus shuffle while the
// window is still coming up.
window.addEventListener("blur", () => api("blurred"));
window.barShow = () => {
  clearTimeout(timer);
  q.value = ""; rows = []; sel = 0; ++seq;
  paint("");
  q.focus();
};
