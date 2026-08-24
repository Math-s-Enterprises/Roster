import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

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
