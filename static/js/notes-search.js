// Search inside notes, in the browser. The server's index holds ciphertext
// for an encrypted note, so it can match no more than the title; here the
// notes are fetched once per opening of the search modal, decrypted with
// the key this browser holds, and matched against the query, and the
// Notes section of the results is drawn from that instead. Plain notes
// are matched the same way, so the section is complete either way.
//
// Nothing decrypted leaves the browser: the server sees the query (it
// always did) and nothing else.

import {
  paramsOf,
  unlock,
  decrypt,
  hasFreshKey,
  getStoredKey,
  refreshKeyTimestamp,
  storeKey,
  KEY_TTL_MS,
} from "./crypto.js";

const SNIPPET_BEFORE = 40;
const SNIPPET_AFTER = 90;

// The notes that hold every word of the query, in title or text, each
// with a snippet of text around the first match (empty when the match is
// in the title alone). A note whose text could not be read (locked) is
// matched by title only.
export function matchNotes(notes, query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  const matches = [];
  for (const note of notes) {
    const title = (note.title || "").toLowerCase();
    const text = (note.text || "").toLowerCase();
    if (!terms.every(function (term) { return title.includes(term) || text.includes(term); })) {
      continue;
    }
    const positions = terms.map(function (term) { return text.indexOf(term); }).filter(function (i) { return i >= 0; });
    matches.push({ note: note, snippet: positions.length ? snippetAround(note.text, Math.min.apply(null, positions), terms) : "" });
  }
  return matches;
}

function snippetAround(text, index, terms) {
  const start = Math.max(0, index - SNIPPET_BEFORE);
  const end = Math.min(text.length, index + SNIPPET_AFTER);
  let piece = text.slice(start, end).replace(/\s+/g, " ").trim();
  if (start > 0) piece = "…" + piece;
  if (end < text.length) piece += "…";
  return piece;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// The Notes section, in the same card markup the server draws
function renderMatches(marker, matches) {
  if (matches.length === 0) {
    marker.innerHTML = "";
    return;
  }
  const cards = matches.map(function (m) {
    const note = m.note;
    const folder = note.folderUrl
      ? '<a href="' + escapeHtml(note.folderUrl) + '" class="search-card-folder"><i class="icon-folder"></i> ' + escapeHtml(note.folderName) + "</a>"
      : "";
    const meta = m.snippet ? '<div class="search-card-meta">' + escapeHtml(m.snippet) + "</div>" : "";
    return (
      '<div class="search-card" data-href="' + escapeHtml(note.url) + '" data-target="_blank">' +
        '<span class="app-badge app-badge-lg badge-gray"><i class="icon-sticky-note"></i></span>' +
        '<div class="search-card-content">' +
          '<div class="search-card-title">' + escapeHtml(note.title) + "</div>" + meta +
        "</div>" + folder +
      "</div>"
    );
  });
  marker.innerHTML =
    '<div class="search-section">' +
      '<div class="search-section-header">' +
        '<span class="search-section-title">Notes</span>' +
        '<span class="app-badge badge-gray">' + matches.length + "</span>" +
      "</div>" +
      '<div class="search-cards">' + cards.join("") + "</div>" +
    "</div>";
}

// Without the key, the encrypted notes can't be searched: say so under
// the server's title matches, with a place to type the passphrase
function renderLocked(marker, onUnlock) {
  if (marker.querySelector(".search-notes-locked")) return;
  const box = document.createElement("div");
  box.className = "search-notes-locked";
  box.innerHTML =
    '<p>Encrypted notes are searched once the key is loaded.</p>' +
    '<div class="search-notes-unlock">' +
      '<input type="password" class="form-control" placeholder="Passphrase" autocomplete="new-password">' +
      '<button type="button" class="btn btn-primary">Unlock</button>' +
    "</div>" +
    '<p class="unlock-error"></p>';
  marker.appendChild(box);
  const input = box.querySelector("input");
  const button = box.querySelector("button");
  const error = box.querySelector(".unlock-error");
  async function go() {
    if (!input.value) return;
    button.disabled = true;
    error.textContent = "";
    try {
      await onUnlock(input.value);
    } catch (e) {
      error.textContent = e.message || "Wrong passphrase.";
      button.disabled = false;
      input.focus();
    }
  }
  button.addEventListener("click", go);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      go();
    }
  });
}

// Keep or restore the "No results found" message as the client's view
// of the notes changes what the results amount to
function settleEmpty(results) {
  const empty = results.querySelector(".search-empty");
  const anySection = results.querySelector(".search-section");
  if (anySection && empty) empty.remove();
  if (!anySection && !empty && !results.querySelector(".search-results-placeholder")) {
    const div = document.createElement("div");
    div.className = "search-empty";
    div.innerHTML = '<i class="icon-search"></i><p>No results found</p>';
    results.appendChild(div);
  }
}

export function init(modal) {
  if (!modal) return;
  const results = modal.querySelector("#search-results");
  const params = paramsOf(modal);
  if (!results || !params.salt) return; // no encryption: the index is complete
  let loaded = null; // one fetch and decryption per opening of the modal

  async function loadNotes(key) {
    const resp = await fetch(modal.dataset.notesUrl, { credentials: "same-origin" });
    const data = await resp.json();
    const notes = [];
    for (const n of data.notes) {
      let text = n.content || "";
      if (n.is_encrypted && text) {
        try {
          text = await decrypt(text, key);
        } catch (e) {
          text = ""; // not under this key; matched by title only
        }
      }
      notes.push({ id: n.id, title: n.title, text: text, url: n.url, folderName: n.folder_name, folderUrl: n.folder_url });
    }
    return notes;
  }

  async function run() {
    const marker = results.querySelector("#search-notes-client");
    if (!marker) return;
    const query = marker.dataset.query || "";
    if (!query || marker.dataset.scopeNotes !== "true") return;
    let key = null;
    if (hasFreshKey(KEY_TTL_MS)) {
      key = await getStoredKey();
      refreshKeyTimestamp();
    }
    if (!key) {
      renderLocked(marker, async function (passphrase) {
        const unlocked = await unlock(passphrase, params);
        await storeKey(unlocked);
        loaded = null;
        await run();
      });
      return;
    }
    loaded = loaded || loadNotes(key);
    const notes = await loaded;
    if (marker.dataset.query !== query || !marker.isConnected) return; // a newer search took over
    renderMatches(marker, matchNotes(notes, query));
    settleEmpty(results);
  }

  results.addEventListener("htmx:afterSwap", run);
  run();
}
