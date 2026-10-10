// Settings › Encryption (templates/settings/encryption.html): every flow
// that touches the passphrase, the note key or the notes' ciphertext.
// All of it runs here in the browser; the server stores salts, sealed
// keys and ciphertext, and never sees a passphrase, a code or a key.
//
// Flows, each behind the passphrase typed into its own field:
//   enable      make a note key, seal it under the passphrase, save
//   change      unseal, reseal under the new passphrase (or, for a key
//               from before the sealed scheme, make a note key and
//               rewrite every encrypted note under it: the upgrade)
//   encrypt all encrypt every plain note; new notes start encrypted
//   recovery    seal the note key under a random code shown once
//   reset       open the recovery seal, set a new passphrase
//   disable     decrypt every note, forget everything

import {
  PBKDF2_ITERATIONS,
  generateSalt,
  deriveKey,
  generateNoteKey,
  wrapKey,
  unwrapKey,
  unlock,
  generateRecoveryCode,
  deriveRecoveryKey,
  encrypt,
  decrypt,
  storeKey,
  hasStoredKey,
  storedKeyMinutesLeft,
  clearStoredKey,
} from "./crypto.js";

const config = JSON.parse(document.getElementById("encryption-config").textContent);
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
const messageEl = document.getElementById("encryption-message");
const progressEl = document.getElementById("encryption-progress");
const progressText = document.getElementById("progress-text");
const sealed = Boolean(config.wrappedKey);

// -- the page ---------------------------------------------------------------

function el(id) {
  return document.getElementById(id);
}

function showMessage(text, isError) {
  messageEl.textContent = text;
  messageEl.classList.toggle("setting-error", isError);
  messageEl.classList.toggle("setting-ok", !isError);
}

function showProgress(text) {
  progressEl.classList.remove("is-hidden");
  progressText.textContent = text;
}

function hideProgress() {
  progressEl.classList.add("is-hidden");
}

function reloadSoon() {
  setTimeout(function () { location.reload(); }, 1200);
}

// Wire a button to an async flow: the button and every other flow
// button are disabled while it runs, errors land in the message line
function flow(buttonId, run) {
  const button = el(buttonId);
  if (!button) return;
  button.addEventListener("click", async function () {
    const buttons = document.querySelectorAll(".encryption-flow");
    buttons.forEach(function (b) { b.disabled = true; });
    // progress and the outcome are shown under the button that was
    // pressed, which may be a long way below the first card
    button.closest(".setting-actions").after(progressEl, messageEl);
    messageEl.textContent = "";
    try {
      await run();
    } catch (e) {
      hideProgress();
      showMessage("Error: " + (e.message || e), true);
      buttons.forEach(function (b) { b.disabled = false; });
    }
  });
}

// Enter in a field presses its button
function submitOnEnter(inputId, buttonId) {
  const input = el(inputId);
  if (input) {
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") el(buttonId).click();
    });
  }
}

function value(id) {
  const input = el(id);
  return input ? input.value : "";
}

// -- the server -------------------------------------------------------------

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!resp.ok) throw new Error("The server refused the change.");
  return resp.json();
}

async function fetchNotes() {
  const resp = await fetch(config.urls.notes, { headers: { "X-CSRFToken": csrfToken } });
  const data = await resp.json();
  return data.notes;
}

async function saveNotes(notes) {
  if (notes.length === 0) return;
  showProgress("Saving " + notes.length + " note(s)...");
  await postJson(config.urls.update, { notes: notes });
}

// The note key for the passphrase typed on this page. A sealed key
// proves the passphrase on its own; the earlier scheme has nothing but
// the notes to prove it against, so the first encrypted one is tried.
async function noteKeyFor(passphrase, notes) {
  if (!passphrase) throw new Error("Please enter your passphrase.");
  const key = await unlock(passphrase, config);
  if (!sealed) {
    const sample = (notes || []).find(function (n) { return n.is_encrypted && n.content; });
    if (sample) {
      try {
        await decrypt(sample.content, key);
      } catch (e) {
        throw new Error("Wrong passphrase.");
      }
    }
  }
  return key;
}

// Seal the note key under a passphrase with a fresh salt and record it
async function sealUnderPassphrase(noteKey, passphrase) {
  const salt = generateSalt();
  const sealingKey = await deriveKey(passphrase, salt, PBKDF2_ITERATIONS);
  const wrapped = await wrapKey(noteKey, sealingKey);
  await postJson(config.urls.saveSalt, {
    salt: salt,
    iterations: PBKDF2_ITERATIONS,
    wrapped_key: wrapped,
  });
}

// Every encrypted note rewritten under a new note key
async function rewriteNotes(notes, oldKey, newKey) {
  const encrypted = notes.filter(function (n) { return n.is_encrypted && n.content; });
  const updates = [];
  for (let i = 0; i < encrypted.length; i++) {
    showProgress("Re-encrypting note " + (i + 1) + " of " + encrypted.length + "...");
    const plaintext = await decrypt(encrypted[i].content, oldKey);
    updates.push({ id: encrypted[i].id, content: await encrypt(plaintext, newKey), is_encrypted: true });
  }
  await saveNotes(updates);
}

function checkNewPassphrase(passphrase, confirm) {
  if (!passphrase) throw new Error("The new passphrase cannot be empty.");
  if (passphrase !== confirm) throw new Error("The new passphrases do not match.");
}

// -- status -------------------------------------------------------------------

const keyStatus = el("key-status");
if (keyStatus) {
  if (hasStoredKey()) {
    keyStatus.innerHTML = '<span class="setting-ok">Loaded (expires in ' + storedKeyMinutesLeft() + ' min)</span>';
  } else {
    keyStatus.textContent = "Not loaded in this browser";
  }
}

const strength = el("strength-status");
if (strength) {
  const rounds = Number(config.iterations).toLocaleString();
  if (!sealed) {
    strength.textContent = rounds + " rounds, key from before the sealed scheme";
  } else if (config.iterations < PBKDF2_ITERATIONS) {
    strength.textContent = rounds + " rounds — change your passphrase to move to " + PBKDF2_ITERATIONS.toLocaleString();
  } else {
    strength.textContent = rounds + " rounds";
  }
}

// -- enable -------------------------------------------------------------------

flow("enable-btn", async function () {
  const passphrase = value("enable-passphrase");
  checkNewPassphrase(passphrase, value("enable-passphrase-confirm"));
  showProgress("Making the key...");
  const noteKey = await generateNoteKey();
  await sealUnderPassphrase(noteKey, passphrase);
  await storeKey(noteKey);
  hideProgress();
  showMessage("Encryption enabled. Use the lock icon in the editor, or encrypt every note below.", false);
  reloadSoon();
});
submitOnEnter("enable-passphrase-confirm", "enable-btn");

// -- change passphrase (and the upgrade from the earlier scheme) --------------

flow("change-btn", async function () {
  const current = value("change-current-passphrase");
  const next = value("change-new-passphrase");
  checkNewPassphrase(next, value("change-confirm-passphrase"));
  showProgress("Checking the passphrase...");
  const notes = sealed ? [] : await fetchNotes();
  const oldKey = await noteKeyFor(current, notes);
  let noteKey = oldKey;
  if (!sealed) {
    // the passphrase-derived key was the note key; give the notes a
    // random key of their own and seal that instead
    noteKey = await generateNoteKey();
    await rewriteNotes(notes, oldKey, noteKey);
  }
  showProgress("Sealing the key under the new passphrase...");
  await sealUnderPassphrase(noteKey, next);
  await storeKey(noteKey);
  hideProgress();
  showMessage(sealed ? "Passphrase changed." : "Passphrase changed and the key moved to the sealed scheme.", false);
  reloadSoon();
});
submitOnEnter("change-confirm-passphrase", "change-btn");

// -- encrypt all notes ----------------------------------------------------------

flow("encrypt-all-btn", async function () {
  showProgress("Checking the passphrase...");
  const noteKey = await noteKeyFor(value("encrypt-all-passphrase"));
  showProgress("Fetching notes...");
  const notes = await fetchNotes();
  const plain = notes.filter(function (n) { return !n.is_encrypted; });
  const updates = [];
  for (let i = 0; i < plain.length; i++) {
    showProgress("Encrypting note " + (i + 1) + " of " + plain.length + "...");
    updates.push({ id: plain[i].id, content: await encrypt(plain[i].content || "", noteKey), is_encrypted: true });
  }
  await saveNotes(updates);
  await postJson(config.urls.byDefaultOn, {});
  await storeKey(noteKey);
  hideProgress();
  showMessage("Every note is encrypted, and new notes will be.", false);
  reloadSoon();
});
submitOnEnter("encrypt-all-passphrase", "encrypt-all-btn");

// -- recovery code --------------------------------------------------------------

async function makeRecoveryCode(passphrase) {
  showProgress("Checking the passphrase...");
  const noteKey = await noteKeyFor(passphrase);
  showProgress("Making the recovery code...");
  const code = generateRecoveryCode();
  const salt = generateSalt();
  const sealingKey = await deriveRecoveryKey(code, salt, config.iterations);
  const wrapped = await wrapKey(noteKey, sealingKey);
  await postJson(config.urls.recovery, { recovery_salt: salt, recovery_wrapped_key: wrapped });
  hideProgress();
  // shown once; the page is not reloaded until the user says they have it
  el("recovery-code").textContent = code;
  el("recovery-shown").classList.remove("is-hidden");
  el("recovery-make").classList.add("is-hidden");
}

flow("recovery-make-btn", function () {
  return makeRecoveryCode(value("recovery-passphrase"));
});
submitOnEnter("recovery-passphrase", "recovery-make-btn");

const recoveryDone = el("recovery-done-btn");
if (recoveryDone) {
  recoveryDone.addEventListener("click", function () { location.reload(); });
}

const recoveryCopy = el("recovery-copy-btn");
if (recoveryCopy) {
  recoveryCopy.addEventListener("click", async function () {
    try {
      await navigator.clipboard.writeText(el("recovery-code").textContent);
      showMessage("Recovery code copied.", false);
    } catch (e) {
      showMessage("Select the code and copy it by hand.", true);
    }
  });
}

flow("recovery-remove-btn", async function () {
  const confirmed = await window.showConfirm({
    title: "Remove Recovery Code",
    message: "Without a recovery code, a forgotten passphrase loses every encrypted note. Continue?",
    confirmText: "Remove",
    isDangerous: true,
  });
  if (!confirmed) {
    document.querySelectorAll(".encryption-flow").forEach(function (b) { b.disabled = false; });
    return;
  }
  await postJson(config.urls.recovery, {});
  showMessage("Recovery code removed.", false);
  reloadSoon();
});

// -- forgot the passphrase: open the recovery seal, set a new one --------------

flow("reset-btn", async function () {
  const code = value("reset-code");
  const next = value("reset-new-passphrase");
  if (!code) throw new Error("Please enter the recovery code.");
  checkNewPassphrase(next, value("reset-confirm-passphrase"));
  showProgress("Checking the recovery code...");
  const sealingKey = await deriveRecoveryKey(code, config.recoverySalt, config.iterations);
  let noteKey;
  try {
    noteKey = await unwrapKey(config.recoveryWrappedKey, sealingKey);
  } catch (e) {
    throw new Error("That recovery code does not open the key.");
  }
  showProgress("Sealing the key under the new passphrase...");
  await sealUnderPassphrase(noteKey, next);
  await storeKey(noteKey);
  hideProgress();
  showMessage("Passphrase reset. Your recovery code still works.", false);
  reloadSoon();
});
submitOnEnter("reset-confirm-passphrase", "reset-btn");

// -- disable ----------------------------------------------------------------------

flow("disable-btn", async function () {
  const passphrase = value("disable-passphrase");
  if (!passphrase) throw new Error("Please enter your passphrase.");
  const confirmed = await window.showConfirm({
    title: "Disable Encryption",
    message: "This will decrypt every encrypted note and store it as plain text. Continue?",
    confirmText: "Disable Encryption",
    isDangerous: true,
  });
  if (!confirmed) {
    document.querySelectorAll(".encryption-flow").forEach(function (b) { b.disabled = false; });
    return;
  }
  showProgress("Fetching notes...");
  const notes = await fetchNotes();
  const noteKey = await noteKeyFor(passphrase, notes);
  const encrypted = notes.filter(function (n) { return n.is_encrypted && n.content; });
  const updates = [];
  for (let i = 0; i < encrypted.length; i++) {
    showProgress("Decrypting note " + (i + 1) + " of " + encrypted.length + "...");
    updates.push({ id: encrypted[i].id, content: await decrypt(encrypted[i].content, noteKey), is_encrypted: false });
  }
  // notes that were marked encrypted while empty
  notes.filter(function (n) { return n.is_encrypted && !n.content; }).forEach(function (n) {
    updates.push({ id: n.id, content: "", is_encrypted: false });
  });
  await saveNotes(updates);
  showProgress("Clearing encryption settings...");
  await postJson(config.urls.clearSalt, {});
  clearStoredKey();
  hideProgress();
  showMessage("Encryption disabled. Every note is plain text.", false);
  reloadSoon();
});
submitOnEnter("disable-passphrase", "disable-btn");
