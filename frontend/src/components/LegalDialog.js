import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "@/styles/legal.css";
import { DOCS, LegalDocument, LegalNavProvider } from "@/components/LegalText";

/**
 * The Terms of Service or the Privacy Policy, in a small dialog over the form.
 *
 * Opened from the sign-up form, so it must never navigate: a new page would
 * throw away what has been typed. Opening it also never ticks the agreement
 * box — reading the terms and agreeing to them are two separate acts.
 *
 * The two documents can be swapped from inside the dialog, because each
 * refers to the other. The text itself lives in LegalText.js, shared with the
 * full /terms and /privacy pages.
 *
 * Built like the app's other dialogs, so the keyboard works the same way:
 *   - Focus moves in on open — to the text itself, so the arrow keys scroll it
 *     at once — and goes back to whatever opened it on close.
 *   - Tab stays inside and wraps; Escape closes; so does a click on the
 *     backdrop, but not a drag that began inside the dialog and ended outside.
 *   - The text is a labelled, focusable region, because a scrolling area that
 *     cannot be reached by keyboard cannot be read by keyboard.
 *   - Page scroll is locked while it is open.
 */

const FOCUSABLE = 'button:not([disabled]), a[href], [tabindex="0"]';

export default function LegalDialog({ kind: initialKind, onClose }) {
  const [kind, setKind] = useState(initialKind);
  const doc = DOCS[kind];
  const panelRef = useRef(null);
  const bodyRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const titleId = useId();

  useEffect(() => {
    const opener = document.activeElement;
    bodyRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  }, []);

  // The other document starts at its top, with focus on its text.
  const showOther = useCallback((next) => {
    setKind(next);
    requestAnimationFrame(() => {
      if (bodyRef.current) {
        bodyRef.current.scrollTop = 0;
        bodyRef.current.focus();
      }
    });
  }, []);

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const panel = panelRef.current;
    const stops = panel ? [...panel.querySelectorAll(FOCUSABLE)] : [];
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

  return createPortal(
    <div
      className="legal-scrim"
      onKeyDown={onKeyDown}
      onMouseDown={(event) => { downOnBackdrop.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        if (downOnBackdrop.current && event.target === event.currentTarget) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        className="legal-dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="legal-dlg-head">
          <h2 id={titleId} className="legal-dlg-title">{doc.title}</h2>
          <button
            type="button"
            className="legal-dlg-close"
            data-testid="legal-close"
            onClick={onClose}
          >
            Close
          </button>
        </header>

        <div
          ref={bodyRef}
          className="legal-dlg-body"
          data-testid="legal-body"
          role="region"
          aria-label={`${doc.title}, full text`}
          tabIndex={0}
        >
          <LegalNavProvider value={{ open: showOther }}>
            <LegalDocument kind={kind} />
          </LegalNavProvider>
        </div>
      </div>
    </div>,
    document.body,
  );
}
