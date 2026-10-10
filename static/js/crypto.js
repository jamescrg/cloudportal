// E2E encryption utilities using Web Crypto API
// AES-256-GCM with PBKDF2 key derivation

// Rounds for a key made now (enable, change passphrase). A user's own
// count is stored beside their salt on the server, since every note
// they hold was encrypted under a key derived with it; raising this
// number only reaches a user when they change their passphrase.
export const PBKDF2_ITERATIONS = 600000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const SESSION_KEY = "notes_encryption_key";

// How long the stored key lives without being used; each use (opening or
// saving an encrypted note) starts it again. It measures idle time at
// this browser, nothing else: the server never holds the key
export const KEY_TTL_MS = 60 * 60 * 1000; // an hour

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
    { name: "AES-GCM", length: 256 },
    true, // extractable for JWK export
    ["encrypt", "decrypt"]
  );
}

// Encrypt plaintext string, returns base64(iv || ciphertext)
export async function encrypt(plaintext, key) {
  const enc = new TextEncoder();
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));

  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv },
    key,
    enc.encode(plaintext)
  );

  // Prepend IV to ciphertext
  const combined = new Uint8Array(IV_BYTES + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), IV_BYTES);

  return uint8ToBase64(combined);
}

// Decrypt base64(iv || ciphertext), returns plaintext string. Throws on wrong key.
export async function decrypt(encoded, key) {
  const combined = base64ToUint8(encoded);

  const iv = combined.slice(0, IV_BYTES);
  const ciphertext = combined.slice(IV_BYTES);

  const plainBuffer = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv },
    key,
    ciphertext
  );

  return new TextDecoder().decode(plainBuffer);
}

// Key management: the derived key is kept in localStorage as a JWK with
// the time it was last used, so a note opens without the passphrase for
// KEY_TTL_MS after the last use (an hour). Past that the key is removed the next
// time anything asks for it, so an expired key never lingers on disk;
// the logout form clears it too (templates/base.html).
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
  return crypto.subtle.importKey(
    "jwk",
    stored.jwk,
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );
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
