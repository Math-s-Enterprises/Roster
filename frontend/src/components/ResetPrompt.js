import React, { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import "@/styles/login-guard.css";

/**
 * The pop-up the sign-in page shows after repeated wrong passwords: the 3rd offers
 * the password reset, the 5th says sign-in is paused and offers it again.
 *
 * IT STANDS ON ITS OWN. An earlier version borrowed the app's shared confirmation
 * dialog, which another developer owns and may change or replace; when that file was
 * swapped, the sign-in page lost the helper it relied on. This one has its own markup
 * and its own styles (in login-guard.css) and depends on nothing else in the app, so
 * nothing done to the shared dialog can break it.
 *
 * The sign-in page is always light, so the palette is the sign-in page's, written out
 * in the stylesheet: this is drawn into <body>, outside the page's own scope.
 *
 * Built like the app's other dialogs, so the keyboard works the same way:
 *   - Focus moves to "Reset password" on open (it only goes to the reset page, so it
 *     is safe to land on) and goes back to what had it on close.
 *   - Tab stays inside and wraps; Escape closes; a click on the backdrop closes, but
 *     not a drag that began inside the dialog and ended outside it.
 *   - Page scroll is locked while it is open.
 */
export default function ResetPrompt({ paused, failures, minutes, onReset, onClose }) {
  const panelRef = useRef(null);
  const resetRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const opener = document.activeElement;
    resetRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  }, []);

  // Escape and Tab are heard for the whole page while this is open, not only inside it,
  // so they still work if focus has slipped to the page behind.
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      const stops = panel ? [...panel.querySelectorAll("button:not([disabled])")] : [];
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (active === panel || !panel.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="lg-scrim"
      onMouseDown={(event) => { downOnBackdrop.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        if (downOnBackdrop.current && event.target === event.currentTarget) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        className="lg-dlg"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
      >
        <h2 id={titleId} className="lg-dlg-title">
          {paused ? "Too many wrong attempts" : "Forgotten your password?"}
        </h2>
        <p id={bodyId} className="lg-dlg-body">
          {paused
            ? `For your security, sign-in is paused for ${minutes} minutes. Reset your password to get back in now.`
            : `That is ${failures} wrong passwords in a row. You can reset it now, or keep trying.`}
        </p>
        <div className="lg-dlg-acts">
          <button
            ref={resetRef}
            type="button"
            className="lg-dlg-primary"
            data-testid="reset-prompt-reset"
            onClick={onReset}
          >
            Reset password
          </button>
          <button
            type="button"
            className="lg-dlg-secondary"
            data-testid="reset-prompt-close"
            onClick={onClose}
          >
            {paused ? "Close" : "Keep trying"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
