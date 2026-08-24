import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
export const API = `${BACKEND_URL}/api`;

const TOKEN_KEY = "roster_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// One interceptor attaches the token to every request, so no individual call
// site can forget it.
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// A 401 means the stored token is expired or invalid — drop it so the app
// falls back to the login screen instead of retrying with a dead credential.
// Login/signup failures are excluded: a wrong password is not a dead session,
// and the form needs to show its own error.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url || "";
    const isAuthAttempt = /\/auth\/(login|signup|google)$/.test(url);
    if (status === 401 && !isAuthAttempt) clearToken();
    return Promise.reject(error);
  },
);

/** Human-readable message from an axios error, whatever shape it arrives in. */
export function errorMessage(error, fallback = "Something went wrong") {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of {loc, msg, type}.
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d.msg).filter(Boolean).join("; ") || fallback;
  }
  // Our own rule failures: {message, reasons[]}.
  if (detail && typeof detail === "object") {
    if (Array.isArray(detail.reasons) && detail.reasons.length) {
      return detail.reasons.join(" ");
    }
    if (detail.message) return detail.message;
  }
  return error?.message || fallback;
}

/**
 * The list of reasons a change was refused, if the server gave one.
 *
 * Returns null for anything else, so a caller can fall back to a toast
 * rather than opening an empty dialog.
 */
export function refusalReasons(error) {
  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)
      && Array.isArray(detail.reasons) && detail.reasons.length) {
    return { message: detail.message || "That change is not allowed.", reasons: detail.reasons };
  }
  return null;
}

export const roleClass = (role) =>
  `role-${(role || "").toLowerCase().replace(/\s+/g, "-")}`;

/**
 * Seniority colour for a role, as a hex value.
 *
 * Used for the 3px accent bar on roster cells. The grid has ~200 cells, so
 * they cannot each be a filled colour block — the accent carries the role and
 * the cell stays white and legible. Matches the ink ramp in index.css: colour
 * encodes seniority, not identity, so it must read as one gradient rather
 * than five unrelated hues.
 */
const ROLE_ACCENTS = [
  [/manager/i, "#ededed"],
  [/supervisor|sup\b/i, "#a1a1a1"],
  [/goods|cashier/i, "#6b6b6b"],
  [/night/i, "#4a4a4a"],
];

export function roleAccent(role) {
  const match = ROLE_ACCENTS.find(([pattern]) => pattern.test(role || ""));
  return match ? match[1] : "#3a3a3a";
}

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const DAY_LABELS = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday",
};

export const DAY_SHORT = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu",
  fri: "Fri", sat: "Sat", sun: "Sun",
};

/**
 * Length of a shift in hours, handling the overnight wrap.
 * Mirrors shift_duration_minutes() on the backend — if you change the rule
 * in one place, change it in the other.
 *
 * Returns 0 for anything without both times. Paid-holiday and unpaid-leave
 * entries are stored with empty start/end, and arithmetic on those produced
 * NaN, which then spread through every total that touched them — the weekly
 * hours column, the CSV and the PDF all showed "NaNh" for anyone on leave.
 */
export function shiftHours(start, end) {
  if (!start || !end) return 0;
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const startMin = sh * 60 + sm;
  const endMin = eh * 60 + em;
  if (!Number.isFinite(startMin) || !Number.isFinite(endMin)) return 0;
  if (endMin === startMin) return 0;
  const minutes = endMin > startMin ? endMin - startMin : 24 * 60 - startMin + endMin;
  return minutes / 60;
}

/**
 * Paid hours for a stored shift — what the person is actually paid for.
 *
 * Prefers the figure the backend computed, because it is the one payroll
 * uses and it is the only one that exists for a holiday entry (which has no
 * times at all). Falls back to the span for older rosters saved before
 * paid_hours was recorded.
 */
export function shiftPaidHours(shift) {
  if (!shift) return 0;
  if (Number.isFinite(shift.paid_hours)) return shift.paid_hours;
  return shiftHours(shift.start, shift.end);
}

export function dateForDay(weekStart, dayKey) {
  const date = new Date(`${weekStart}T00:00:00`);
  date.setDate(date.getDate() + DAYS.indexOf(dayKey));
  return date;
}

export function fmtDayDate(date) {
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

/** The Monday of the week containing `dateStr` (or today). */
export function mondayOf(dateStr) {
  const date = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date();
  const weekday = date.getDay(); // 0 = Sunday
  date.setDate(date.getDate() + (weekday === 0 ? -6 : 1 - weekday));
  // Build the string from local parts: toISOString() converts to UTC and can
  // shift the date across a day boundary depending on the timezone.
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export const fmtHours = (value) => `${Number(value || 0).toFixed(1)}h`;

/**
 * Money, in one place.
 *
 * Every currency string used to be hand-written at the call site, and one of
 * them said "$" while the rest said "€" — the kind of drift that is invisible
 * until somebody spots it on a cost report. Anything showing an amount goes
 * through here.
 *
 * Missing and malformed values render as 0 rather than "NaN" or "undefined",
 * because a roster saved before labor_cost existed should not print rubbish.
 */
export const CURRENCY = "€";

export function fmtMoney(value, { decimals = 0 } = {}) {
  const amount = Number(value);
  return `${CURRENCY}${(Number.isFinite(amount) ? amount : 0).toFixed(decimals)}`;
}
