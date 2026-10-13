import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import { useSonner } from "sonner";

/**
 * A short memory for the pop-up messages.
 *
 * Every pop-up the app shows ("Saved", "Could not load the report", …) is
 * also kept here: the latest 20, newest first. When a 21st arrives the oldest
 * drops off. The Notifications drawer in the sidebar reads this list, so what
 * you did a few minutes ago is still there after the message has faded.
 *
 * HOW IT SEES EVERY POP-UP WITHOUT TOUCHING THE PAGES
 *
 * The app shows about 130 pop-ups from 16 files, each by calling sonner's
 * `toast`. Rather than change every call, <Recorder> listens through sonner's
 * own `useSonner` hook, which is handed every toast as it is created —
 * success, error, warning and the plain, untyped kind alike. A new page that
 * calls `toast` is recorded with no extra work.
 *
 * Two behaviours of `useSonner` shape the code:
 *   - Its list only grows. A toast that has faded stays in it, so "what is
 *     new" cannot be read off the list; the Recorder remembers each toast it
 *     has already kept, by id.
 *   - A toast can be updated in place under the same id (a "Saving…" that
 *     becomes "Saved"). The Recorder keeps the outcome and not the loading
 *     step, and keeps an update only when its content actually changed.
 *
 * SIGNING OUT DOES NOT CLEAR IT
 *
 * Sign out and sign back in and the same twenty are still there: the point of
 * the list is to look back at what was done, and that includes yesterday. It is
 * cleared only by "Clear all", or as newer messages push the oldest out.
 *
 * (An earlier version cleared it at sign-out, and kept it in sessionStorage when
 * "Keep me signed in" was unticked. Both made it vanish on sign-in. The second
 * was subtler: signing out removes the token, so the code could no longer tell
 * which storage to look in, and fell back to the wrong one.)
 *
 * PRIVACY
 *
 * These messages name people ("Recorded for Aoife", "Removed Aaron's shift"),
 * and some concern sick leave, so the list is still treated as personal data:
 *   - It is kept per signed-in user, so another account on the same browser
 *     never sees it.
 *   - It stays on this device, in localStorage, until it is cleared.
 * The cost of keeping it past sign-out is that on a shared computer it stays in
 * that browser until cleared. Anyone sharing a computer can press "Clear all"
 * first. The Privacy Policy says this.
 */

export const MAX_NOTIFICATIONS = 20;

const KEY_PREFIX = "roster_notifications:";
const VERSION = 1;
const KINDS = ["success", "error", "warning", "info"];

// --- storage ---------------------------------------------------------------

/**
 * Always localStorage, whatever the sign-in is stored in, so the list is looked for
 * in the same place before and after a sign-out. Null if storage is blocked
 * (private browsing): then the list lives in memory for the session.
 */
function storeFor() {
  try {
    return localStorage;
  } catch {
    return null;
  }
}

const isEntry = (e) => Boolean(e)
  && typeof e.id === "string"
  && typeof e.message === "string"
  && KINDS.includes(e.kind)
  && Number.isFinite(e.at)
  && (e.description === undefined || typeof e.description === "string");

/** Newest first, capped. Pure, so the cap is one rule in one place. */
export function addNotification(list, entry) {
  return [entry, ...list].slice(0, MAX_NOTIFICATIONS);
}

const newestAt = (items) => items.reduce((n, i) => Math.max(n, i.at), 0);

function readState(key) {
  const empty = { items: [], seenAt: 0 };
  const store = key && storeFor();
  if (!store) return empty;
  try {
    const parsed = JSON.parse(store.getItem(key));
    if (!parsed || parsed.v !== VERSION || !Array.isArray(parsed.items)) return empty;
    const items = parsed.items.filter(isEntry).slice(0, MAX_NOTIFICATIONS);
    // Anything stored without a "last looked" time counts as already seen,
    // rather than flashing a badge for messages from a previous visit.
    const seenAt = Number.isFinite(parsed.seenAt) ? parsed.seenAt : newestAt(items);
    return { items, seenAt };
  } catch {
    return empty; // missing, unparseable or tampered: start clean
  }
}

function writeState(key, state) {
  const store = key && storeFor();
  if (!store) return;
  try {
    if (state.items.length === 0) store.removeItem(key);
    else store.setItem(key, JSON.stringify({ v: VERSION, seenAt: state.seenAt, items: state.items }));
  } catch {
    /* quota or blocked: the list still works for this session */
  }
}

/** Remove from both storages, which also tidies up anything an earlier version left in sessionStorage. */
function removeState(key) {
  if (!key) return;
  [() => localStorage, () => sessionStorage].forEach((get) => {
    try { get().removeItem(key); } catch { /* nothing to remove */ }
  });
}

// --- time ------------------------------------------------------------------

const clock = (date) => date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** "Just now", "12 min ago", "Today 14:32", "Yesterday 09:05", "Mon 6 Oct, 14:32". */
export function formatWhen(at, now = Date.now()) {
  const date = new Date(at);
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 45) return "Just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;

  const midnight = new Date(now); midnight.setHours(0, 0, 0, 0);
  const dayMs = 86400000;
  if (at >= midnight.getTime()) return `Today ${clock(date)}`;
  if (at >= midnight.getTime() - dayMs) return `Yesterday ${clock(date)}`;
  const day = date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${clock(date)}`;
}

// --- the recorder ----------------------------------------------------------

let counter = 0;
const nextId = () => `n${Date.now().toString(36)}-${(counter += 1)}`;

const textOf = (value) => {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  return ""; // a React node: nothing sensible to store as text
};

function Recorder({ onRecord }) {
  const { toasts } = useSonner();
  // toast id -> signature of what was last kept for it
  const kept = useRef(new Map());

  useEffect(() => {
    const fresh = [];
    // Newest first in the list, so walk backwards to add oldest first and
    // leave the newest on top.
    for (let i = toasts.length - 1; i >= 0; i -= 1) {
      const toast = toasts[i];
      if (toast.type === "loading") continue; // keep the outcome, not "Saving…"
      const message = textOf(toast.title) || "Notification";
      const description = textOf(toast.description);
      const signature = `${toast.type || ""}|${message}|${description}`;
      if (kept.current.get(toast.id) === signature) continue;
      kept.current.set(toast.id, signature);
      fresh.push({
        id: nextId(),
        kind: KINDS.includes(toast.type) ? toast.type : "info",
        message,
        ...(description ? { description } : {}),
        at: Date.now(),
      });
    }
    if (fresh.length > 0) onRecord(fresh);
  }, [toasts, onRecord]);

  return null;
}

// --- the provider ----------------------------------------------------------

const NONE = { items: [], unread: 0, markAllRead() {}, clear() {} };
const NotificationsContext = createContext(NONE);

export function NotificationsProvider({ userId, children }) {
  const key = userId ? `${KEY_PREFIX}${userId}` : null;
  const [loadedFor, setLoadedFor] = useState(key);
  const [state, setState] = useState(() => readState(key));

  // A different user on the same mounted layout: load theirs, not the last
  // person's. (Adjusting state during render is React's documented way to
  // reset state when a prop changes.)
  if (loadedFor !== key) {
    setLoadedFor(key);
    setState(readState(key));
  }

  useEffect(() => { writeState(key, state); }, [key, state]);

  const record = useCallback((entries) => {
    setState((current) => ({
      ...current,
      items: entries.reduce(addNotification, current.items),
    }));
  }, []);

  const markAllRead = useCallback(() => {
    setState((current) => {
      const newest = newestAt(current.items);
      if (newest <= current.seenAt) return current; // nothing unread: no re-render
      return { ...current, seenAt: Math.max(Date.now(), newest) };
    });
  }, []);

  const clear = useCallback(() => {
    setState({ items: [], seenAt: Date.now() });
    removeState(key);
  }, [key]);

  const unread = state.items.filter((item) => item.at > state.seenAt).length;
  const value = useMemo(
    () => ({ items: state.items, unread, markAllRead, clear }),
    [state.items, unread, markAllRead, clear],
  );

  return (
    <NotificationsContext.Provider value={value}>
      <Recorder onRecord={record} />
      {children}
    </NotificationsContext.Provider>
  );
}

/** Outside a provider this is an empty, inert list, so nothing crashes. */
export function useNotifications() {
  return useContext(NotificationsContext);
}
