import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("roster_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const roleClass = (role) => {
  const r = (role || "").toLowerCase().replace(/\s+/g, "-");
  return `role-${r}`;
};

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const DAY_LABELS = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };
export const DAY_SHORT = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

export function shiftHours(start, end) {
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const s = sh * 60 + sm, e = eh * 60 + em;
  return (e > s ? e - s : (24 * 60 - s) + e) / 60;
}

export function dateForDay(weekStart, dayKey) {
  const idx = DAYS.indexOf(dayKey);
  const d = new Date(weekStart + "T00:00:00");
  d.setDate(d.getDate() + idx);
  return d;
}

export function fmtDayDate(d) {
  return d.toLocaleDateString("en-US", { day: "2-digit", month: "short" });
}

export function mondayOf(dateStr) {
  const d = dateStr ? new Date(dateStr) : new Date();
  const day = d.getDay(); // 0 sun .. 6 sat
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
}

export function fmtHours(v) {
  return `${Number(v || 0).toFixed(1)}h`;
}
