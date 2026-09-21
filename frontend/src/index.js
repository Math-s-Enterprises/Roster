import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

/**
 * Apply the stored theme before anything renders.
 *
 * This used to live in AppLayout, which only mounts once signed in — so
 * the sign-in, forgot-password and reset-password pages never got the
 * attribute, and a reload while signed out dropped back to dark. Doing it
 * here means the choice holds across the whole app, signed in or not, and
 * there is no flash of the wrong theme on first paint.
 */
(function applyStoredTheme() {
  try {
    if (localStorage.getItem("roster_theme") === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    }
  } catch {
    /* storage unavailable (private mode) — dark is the default anyway */
  }
})();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * Open the date/time picker from anywhere in the field, not just the icon.
 *
 * By default only the small calendar glyph opens the picker; clicking the
 * text lands you in whichever segment you hit, which means aiming at a 16px
 * target to pick a week. One delegated listener covers every date input in
 * the app, including ones rendered later.
 *
 * showPicker() throws if the browser blocks it (no user gesture, or the
 * input is disabled), and is absent in older Safari — either way the native
 * icon still works, so failure is silent by design.
 */
document.addEventListener("click", (event) => {
  const field = event.target;
  if (!(field instanceof HTMLInputElement)) return;
  if (field.type !== "date" && field.type !== "time") return;
  if (field.disabled || field.readOnly) return;
  try {
    field.showPicker?.();
  } catch {
    /* browser declined — the icon still opens it */
  }
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
