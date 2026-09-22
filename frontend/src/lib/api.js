import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
export const API = `${BACKEND_URL}/api`;

const TOKEN_KEY = "roster_token";

/*
 * Where the token lives is what "Keep me signed in" controls.
 *
 * localStorage survives closing the browser; sessionStorage is cleared when
 * it closes. Email and Google sign-in authenticate only with this Bearer
 * token — the server reads a session cookie but never sets one — so the
 * choice of store genuinely decides whether you are still signed in
 * tomorrow. The token's own expiry still applies either way.
 *
 * Wrapped in try/catch because storage throws in some private-browsing
 * modes, where the sensible answer is simply "not signed in".
 */
export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

/**
 * `persist` true or false chooses the store; left out, the new token goes
 * wherever the current one already is. That matters for token *replacement*
 * — changing your password issues a fresh token, and defaulting to "keep"
 * would silently turn a session-only sign-in into a remembered one.
 */
export const setToken = (token, persist) => {
  try {
    let keep;
    if (persist === undefined) {
      keep = sessionStorage.getItem(TOKEN_KEY) ? sessionStorage : localStorage;
    } else {
      keep = persist ? localStorage : sessionStorage;
    }
    const drop = keep === localStorage ? sessionStorage : localStorage;
    drop.removeItem(TOKEN_KEY);
    keep.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — the request will simply be unauthenticated */
  }
};

export const clearToken = () => {
  try {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing stored, nothing to clear */
  }
};

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
/**
 * A field name the manager would recognise, from the API's field name.
 *
 * Spelled out where the API name and the on-screen label differ, because
 * "max_weekly_hours: Input should be greater than 0" still leaves somebody
 * hunting for a box called that. Anything unlisted falls back to
 * de-underscoring, which is right often enough and never worse than the raw
 * name.
 */
const FIELD_LABELS = {
  max_weekly_hours: "Weekly hours",
  contract_span_hours: "Contracted hours",
  contract_span_tolerance: "Contract tolerance",
  term_time_max_hours: "Term-time hours",
  summer_break: "Summer break",
  hourly_rate: "Hourly rate",
  opening_holiday_hours: "Holiday allowance",
  min_shift_hours: "Minimum shift length",
  max_shift_hours: "Maximum shift length",
  min_rest_hours: "Rest between shifts",
  age: "Age",
  name: "Name",
  email: "Email",
  role: "Role",
};

function fieldLabel(field) {
  if (!field) return "";
  return FIELD_LABELS[field]
    || field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function errorMessage(error, fallback = "Something went wrong") {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of {loc, msg, type}.
  //
  // NAME THE FIELD. `msg` alone is "Input should be greater than 0", which
  // is true of a form with a dozen numbers on it and useless on all of them
  // — a manager saw exactly that, could not tell which box was wrong, and
  // reasonably assumed the app was broken.
  //
  // `loc` is like ["body", "max_weekly_hours"] or ["body", "summer_break",
  // "max_weekly_hours"], so the last string element is the field and the one
  // before it is the section it sits in.
  if (Array.isArray(detail) && detail.length) {
    const lines = detail
      .map((d) => {
        const path = (d.loc || []).filter(
          (part) => typeof part === "string" && part !== "body"
        );
        const label = fieldLabel(path[path.length - 1]);
        const where = path.length > 1 ? ` (${fieldLabel(path[0])})` : "";
        return label ? `${label}${where}: ${d.msg}` : d.msg;
      })
      .filter(Boolean);
    return lines.join("; ") || fallback;
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

export function availabilityConflict(employee, day, start, end) {
  const availability = employee?.availability;
  if (!availability) return null;
  const name = employee.name || "This employee";
  if (availability.available_days?.length
      && !availability.available_days.includes(day)) {
    return `${name} is not available on ${DAY_LABELS[day]}.`;
  }
  if (availability.earliest_start && start < availability.earliest_start) {
    return `${name} cannot start before ${availability.earliest_start}.`;
  }
  const overnight = end <= start;
  if (availability.latest_finish) {
    const finish = overnight || end === "00:00" ? "24:00" : end;
    const latest = availability.latest_finish === "00:00"
      ? "24:00" : availability.latest_finish;
    if (finish > latest) {
      return `${name} cannot work past ${availability.latest_finish}.`;
    }
  }
  if (overnight && availability.can_work_overnight === false) {
    return `${name} does not work overnight shifts.`;
  }
  return null;
}

/** Return a warning when a work shift overlaps a live leave booking.
 *
 * This reads the holiday records rather than the roster cell, so it also
 * catches a leave booking added after a draft roster was generated.
 */
export function leaveConflict(holidays, employee, weekStart, day) {
  const employeeId = employee?.employee_id;
  if (!employeeId || !weekStart || !DAYS.includes(day)) return null;

  const date = new Date(`${weekStart}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + DAYS.indexOf(day));
  const dateIso = date.toISOString().slice(0, 10);
  const booking = (holidays || []).find((holiday) => (
    holiday.employee_id === employeeId
      && ["employee", "unavailable", "sick"].includes(holiday.scope)
      && holiday.date <= dateIso
      && (holiday.end_date || holiday.date) >= dateIso
  ));
  if (!booking) return null;

  const kind = booking.scope === "employee" ? "paid holiday"
    : booking.scope === "unavailable" ? "unpaid leave" : "sick leave";
  return `${employee.name || "This employee"} is on ${kind} on ${DAY_LABELS[day]}.`;
}

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
 * When the shop setting is supplied, working shifts are recalculated from
 * their times so a setting change takes effect immediately. Holiday entries
 * have no times and therefore keep their stored paid entitlement.
 */
export function shiftPaidHours(shift, breaksArePaid) {
  if (!shift) return 0;
  const isLeave = shift.paid_holiday || shift.unpaid_holiday || shift.sick;
  if (typeof breaksArePaid === "boolean" && shift.start && shift.end && !isLeave) {
    const span = shiftHours(shift.start, shift.end);
    if (breaksArePaid) return span;
    if (Number.isFinite(shift.break_minutes)) {
      return Math.max(0, span - shift.break_minutes / 60);
    }
    if (Number.isFinite(shift.paid_hours)) return shift.paid_hours;
    const breakMinutes = span >= 10 ? 60 : span >= 8 ? 45
      : span >= 6 ? 30 : span >= 5 ? 15 : 0;
    return Math.max(0, span - breakMinutes / 60);
  }
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
