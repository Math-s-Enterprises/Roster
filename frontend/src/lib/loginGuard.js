/**
 * A speed bump for wrong passwords on the sign-in page.
 *
 * After PROMPT_AT wrong passwords in a row for an email address, the page offers
 * to reset the password. After LOCK_AT, sign-in for that address is paused for
 * LOCK_MINUTES and the page points at the reset. A correct password, or choosing
 * to reset, starts the count again.
 *
 * WHAT THIS IS, AND WHAT IT IS NOT
 *
 * It lives in the browser, so it is a courtesy: it nudges an honest person who has
 * forgotten their password towards the reset, and slows them down. It does NOT stop
 * a program that talks to the server directly, because the server itself has no
 * limit on attempts. Only the server can enforce one.
 *
 * Only a wrong password counts (the server answers 401). A dropped connection, a
 * server error, or signing up never does.
 *
 * WHAT IS KEPT
 *
 * A count and a time per email address, in this browser's localStorage so that
 * reloading the page does not reset it. The address itself is not stored, only a
 * short hash of it: that is not security (it is easy to reverse for a known
 * address), only a way of not leaving addresses lying in storage. Entries older
 * than the pause are dropped, and at most MAX_ENTRIES are kept. The Privacy
 * Policy mentions this.
 */

export const PROMPT_AT = 3;
export const LOCK_AT = 5;
export const LOCK_MINUTES = 15;

const WINDOW_MS = LOCK_MINUTES * 60 * 1000;
const STORE_KEY = "roster_login_guard";
const MAX_ENTRIES = 20;

const normalise = (email) => String(email || "").trim().toLowerCase();

/** FNV-1a. Not for security: it keeps the address itself out of storage. */
function idFor(email) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < email.length; i += 1) {
    hash ^= email.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

// If storage is blocked (private browsing) the count still works for this visit.
let memory = {};

const isEntry = (e) => Boolean(e) && Number.isFinite(e.n) && Number.isFinite(e.last) && Number.isFinite(e.until);

function readEntries() {
  let raw;
  try {
    raw = localStorage.getItem(STORE_KEY);
  } catch {
    return memory; // blocked
  }
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.v !== 1 || !parsed.entries || typeof parsed.entries !== "object") return {};
    return Object.fromEntries(Object.entries(parsed.entries).filter(([, entry]) => isEntry(entry)));
  } catch {
    return {}; // unreadable or tampered with: start clean
  }
}

function writeEntries(entries) {
  try {
    if (Object.keys(entries).length === 0) localStorage.removeItem(STORE_KEY);
    else localStorage.setItem(STORE_KEY, JSON.stringify({ v: 1, entries }));
  } catch {
    memory = entries;
  }
}

const NONE = { n: 0, last: 0, until: 0 };

/** What an entry means right now: a finished pause or a stale count is a fresh start. */
function current(entry, now) {
  if (!entry) return NONE;
  if (entry.until > now) return entry;                 // paused
  if (entry.until) return NONE;                        // the pause is over
  if (now - entry.last > WINDOW_MS) return NONE;       // too long ago to count
  return entry;
}

function tidy(entries, now) {
  const live = Object.entries(entries).filter(([, entry]) => current(entry, now) !== NONE);
  live.sort((a, b) => b[1].last - a[1].last);
  return Object.fromEntries(live.slice(0, MAX_ENTRIES));
}

/** { failures, locked, until, remainingMs } for this address, as of `now`. */
export function readGuard(email, now = Date.now()) {
  const key = normalise(email);
  if (!key) return { failures: 0, locked: false, until: 0, remainingMs: 0 };
  const entry = current(readEntries()[idFor(key)], now);
  const locked = entry.until > now;
  return { failures: entry.n, locked, until: entry.until, remainingMs: locked ? entry.until - now : 0 };
}

/** Count one more wrong password. Returns the state afterwards. */
export function recordFailure(email, now = Date.now()) {
  const key = normalise(email);
  if (!key) return readGuard(email, now);
  const entries = tidy(readEntries(), now);
  const id = idFor(key);
  const before = current(entries[id], now);
  if (before.until > now) return readGuard(email, now);   // already paused: nothing more to count
  const n = before.n + 1;
  entries[id] = { n, last: now, until: n >= LOCK_AT ? now + WINDOW_MS : 0 };
  writeEntries(tidy(entries, now));
  return readGuard(email, now);
}

/** A correct password, or going off to reset it, starts the count again. */
export function clearGuard(email) {
  const key = normalise(email);
  if (!key) return;
  const entries = readEntries();
  delete entries[idFor(key)];
  writeEntries(entries);
}

export const minutesLeft = (ms) => Math.max(1, Math.ceil(ms / 60000));
