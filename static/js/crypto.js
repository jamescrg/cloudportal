// Notes encryption, all of it in the browser: AES-256-GCM under one
// random "note key" per user. The note key never reaches the server in
// the clear: the passphrase seals it (PBKDF2 → AES-GCM over the key's
// bytes, the "wrapped key" the server stores beside the salt), and a
// recovery code can seal it a second way. Changing the passphrase
// reseals the key; the notes are untouched.
//
// Users from before the sealed key (a salt but no wrapped key) have
// their notes encrypted under the passphrase-derived key itself;
// unlock() hands that key back for them until a passphrase change
// moves them over (static/js/encryption-settings.js).

// Rounds for a key derived now (enable, change passphrase). A user's own
// count is stored beside their salt, since their wrapped key (or, before
// the sealed key, every note) was made with it.
export const PBKDF2_ITERATIONS = 600000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const SESSION_KEY = "notes_encryption_key";

// How long the stored key lives without being used; each use (opening or
// saving an encrypted note) starts it again. It measures idle time at
// this browser, nothing else: the server never holds the key
export const KEY_TTL_MS = 8 * 60 * 60 * 1000; // eight hours

const AES = { name: "AES-GCM", length: 256 };
const USES = ["encrypt", "decrypt"];

// Generate a random 16-byte salt, returned as base64
export function generateSalt() {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
  return uint8ToBase64(salt);
}

// Derive an AES-256-GCM CryptoKey from passphrase + base64 salt, with
// the round count the key was (or is being) made with. A missing count
// would silently derive a key that opens nothing, so it is required.
export async function deriveKey(passphrase, saltB64, iterations) {
  const rounds = Number(iterations);
  if (!Number.isInteger(rounds) || rounds < 1) {
    throw new Error("Key derivation needs the round count");
  }
  const enc = new TextEncoder();
  const salt = base64ToUint8(saltB64);

  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    enc.encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );

  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt,
      iterations: rounds,
      hash: "SHA-256",
    },
    keyMaterial,
    AES,
    true, // extractable for JWK export
    USES
  );
}

// -- the note key and its seals ---------------------------------------------

// A fresh random note key
export function generateNoteKey() {
  return crypto.subtle.generateKey(AES, true, USES);
}

// The note key sealed under a passphrase- or recovery-derived key, as
// base64(iv || ciphertext) of its raw bytes: what the server stores
export async function wrapKey(noteKey, sealingKey) {
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", noteKey));
  return encryptBytes(raw, sealingKey);
}

// The note key out of its seal. Throws when the sealing key is wrong,
// which is how a passphrase or recovery code is checked.
export async function unwrapKey(wrapped, sealingKey) {
  const raw = await decryptBytes(wrapped, sealingKey);
  return crypto.subtle.importKey("raw", raw, AES, true, USES);
}

// The encryption parameters a page carries on an element's data
// attributes (templates/notes/*.html): the salt, the round count and,
// for a sealed key, the wrapped key
export function paramsOf(element) {
  const data = (element && element.dataset) || {};
  return {
    salt: data.encryptionSalt || "",
    iterations: data.encryptionIterations || "",
    wrappedKey: data.encryptionWrappedKey || "",
  };
}

// The note key for a passphrase: derive the sealing key, and open the
// seal; before the sealed key, the derived key is the note key itself.
// Throws on a wrong passphrase when there is a seal to check it against.
export async function unlock(passphrase, params) {
  const derived = await deriveKey(passphrase, params.salt, params.iterations);
  if (!params.wrappedKey) return derived;
  try {
    return await unwrapKey(params.wrappedKey, derived);
  } catch (e) {
    throw new Error("Wrong passphrase.");
  }
}

// -- recovery codes -----------------------------------------------------------

// A random code the user writes down: 128 bits as 26 letters and digits
// in groups of four, from an alphabet without 0/O or 1/I/L to mistake
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

export function generateRecoveryCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(26));
  let code = "";
  for (let i = 0; i < bytes.length; i++) {
    code += CODE_ALPHABET[bytes[i] % CODE_ALPHABET.length];
  }
  return code.match(/.{1,4}/g).join("-");
}

// A code as typed, forgiving of case, spaces and dashes
export function normalizeRecoveryCode(code) {
  return (code || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

// The sealing key for a recovery code: the same derivation as a
// passphrase, over the normalised code and the recovery salt
export function deriveRecoveryKey(code, saltB64, iterations) {
  return deriveKey(normalizeRecoveryCode(code), saltB64, iterations);
}

// -- notes ----------------------------------------------------------------

// Encrypt plaintext string, returns base64(iv || ciphertext)
export async function encrypt(plaintext, key) {
  return encryptBytes(new TextEncoder().encode(plaintext), key);
}

// Decrypt base64(iv || ciphertext), returns plaintext string. Throws on wrong key.
export async function decrypt(encoded, key) {
  return new TextDecoder().decode(await decryptBytes(encoded, key));
}

async function encryptBytes(bytes, key) {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, bytes);
  const combined = new Uint8Array(IV_BYTES + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), IV_BYTES);
  return uint8ToBase64(combined);
}

async function decryptBytes(encoded, key) {
  const combined = base64ToUint8(encoded);
  const iv = combined.slice(0, IV_BYTES);
  const ciphertext = combined.slice(IV_BYTES);
  return crypto.subtle.decrypt({ name: "AES-GCM", iv: iv }, key, ciphertext);
}

// -- the key this browser holds ---------------------------------------------
// The note key is kept in localStorage as a JWK with the time it was
// last used, so a note opens without the passphrase for KEY_TTL_MS after
// the last use. Past that the key is removed the next time anything asks
// for it, so an expired key never lingers on disk; the logout form
// clears it too (templates/base.html).

function readStoredKey(ttlMs = KEY_TTL_MS) {
  let raw;
  try {
    raw = localStorage.getItem(SESSION_KEY);
  } catch (e) {
    return null;
  }
  if (!raw) return null;
  let stored = null;
  try {
    stored = JSON.parse(raw);
  } catch (e) { /* not ours */ }
  const fresh = stored && stored.jwk && stored.timestamp
    && (Date.now() - stored.timestamp) < ttlMs;
  if (!fresh) {
    clearStoredKey();
    return null;
  }
  return stored;
}

export function hasStoredKey() {
  return readStoredKey() !== null;
}

export function hasFreshKey(ttlMs) {
  return readStoredKey(ttlMs) !== null;
}

// How many whole minutes the stored key has left, or 0 when there is none
export function storedKeyMinutesLeft() {
  const stored = readStoredKey();
  if (!stored) return 0;
  return Math.max(0, Math.round((KEY_TTL_MS - (Date.now() - stored.timestamp)) / 60000));
}

export function refreshKeyTimestamp() {
  const stored = readStoredKey();
  if (!stored) return;
  stored.timestamp = Date.now();
  localStorage.setItem(SESSION_KEY, JSON.stringify(stored));
}

export async function getStoredKey() {
  const stored = readStoredKey();
  if (!stored) return null;
  return crypto.subtle.importKey("jwk", stored.jwk, AES, true, USES);
}

export async function storeKey(key) {
  const jwk = await crypto.subtle.exportKey("jwk", key);
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    jwk: jwk,
    timestamp: Date.now(),
  }));
}

export function clearStoredKey() {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch (e) { /* nothing to clear */ }
}

// Base64 helpers
function uint8ToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToUint8(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}
