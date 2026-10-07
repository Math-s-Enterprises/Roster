import React, {
  createContext, useCallback, useContext, useEffect, useId, useRef, useState,
} from "react";
import { createPortal } from "react-dom";

/**
 * Themed confirmation dialogs, in place of window.confirm.
 *
 * The browser's own confirm box is drawn by the browser: its font, its
 * colours, its position, none of which follow the app or its light and dark
 * themes. This is a dialog we draw ourselves, in the same measurements as the
 * Dashboard's reset dialog.
 *
 * There are two ways in, and both draw the same dialog.
 *
 * 1. The component, which the AI Rules, Fixed Shifts and Sick Report pages
 *    already use. Mount it while there is something to confirm:
 *
 *        {deleting && <ConfirmDialog
 *          title={`Remove ${deleting.title}?`}
 *          description="Rosters already generated are unchanged."
 *          onClose={() => setDeleting(null)}
 *          onConfirm={() => remove(deleting)} />}
 *
 *    onConfirm may be async. While it runs, both buttons are disabled so it
 *    cannot be submitted twice, and onClose is called when it finishes — so a
 *    page does not have to close the dialog itself, though it may.
 *
 * 2. The hook, where one line replaces the native call:
 *
 *        const confirm = useConfirm();
 *        if (!(await confirm({ title: "Remove Deli?", body: "…" }))) return;
 *
 *    This needs <ConfirmProvider> above it. Without one it falls back to
 *    window.confirm, which fails safe — it still asks — where throwing would
 *    break the page and returning true would delete without asking.
 *
 * Replacing a native control means owning what it gave for free:
 *
 *   - Cancel is focused first. For a destructive action the safe default is
 *     the one that does nothing, so a stray Enter cancels.
 *   - Tab stays inside the dialog and wraps; Escape cancels.
 *   - Clicking the backdrop cancels — but not when a click began inside the
 *     dialog and ended outside it, which is what dragging to select text does.
 *   - Focus returns to whatever opened it. If that element has since gone (the
 *     row was removed), focus is left alone rather than thrown somewhere odd.
 *   - Background scroll is locked while it is open and restored after.
 *
 * The hook route also cancels an open prompt when a second one arrives, and
 * when the provider unmounts, so no awaited promise is ever left hanging.
 */

const ConfirmContext = createContext(null);

/** The fallback: still asks, in the browser's own style. */
const nativeConfirm = (options) => Promise.resolve(
  window.confirm([options.title, options.body, options.detail].filter(Boolean).join("\n\n")),
);

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const pending = useRef(null);
  const opener = useRef(null);
  const counter = useRef(0);

  const settle = useCallback((answer) => {
    const current = pending.current;
    if (!current) return;
    pending.current = null;
    setRequest(null);

    const element = opener.current;
    opener.current = null;
    if (element && element.isConnected && typeof element.focus === "function") {
      element.focus();
    }
    current.resolve(answer);
  }, []);

  const confirm = useCallback((options) => new Promise((resolve) => {
    if (pending.current) {
      // Keep the original opener: by now activeElement is inside the dialog.
      pending.current.resolve(false);
    } else {
      opener.current = document.activeElement;
    }
    counter.current += 1;
    const next = { ...options, resolve, id: counter.current };
    pending.current = next;
    setRequest(next);
  }), []);

  useEffect(() => () => {
    if (pending.current) {
      pending.current.resolve(false);
      pending.current = null;
    }
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {request && createPortal(
        <Dialog
          key={request.id}
          title={request.title}
          body={request.body}
          detail={request.detail}
          confirmLabel={request.confirmLabel}
          cancelLabel={request.cancelLabel}
          tone={request.tone}
          // The provider returns focus itself, so a replaced prompt keeps the
          // original opener rather than the dialog it replaced.
          restoreFocus={false}
          onConfirm={() => settle(true)}
          onCancel={() => settle(false)}
        />,
        document.body,
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmContext) || nativeConfirm;
}

/**
 * The component form. Mount it to ask, unmount it (or let onClose do so) to
 * stop. `description` is the same text as `body`; either works.
 */
export default function ConfirmDialog({
  title,
  description,
  body,
  detail,
  children,
  confirmLabel = "Remove",
  cancelLabel = "Cancel",
  tone = "danger",
  onConfirm,
  onClose,
}) {
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const run = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onConfirm?.();
    } catch (error) {
      // The page's own handler normally reports its failures. Logging here
      // keeps one that slips through from becoming an unhandled rejection —
      // the dev overlay shows those as a full-screen error.
      // eslint-disable-next-line no-console
      console.error("ConfirmDialog: onConfirm failed", error);
    } finally {
      // The page may already have unmounted this by clearing its own state.
      if (mounted.current) setBusy(false);
      onClose?.();
    }
  };

  return createPortal(
    <Dialog
      title={title}
      body={body ?? description}
      detail={detail}
      confirmLabel={confirmLabel}
      cancelLabel={cancelLabel}
      tone={tone}
      busy={busy}
      onConfirm={run}
      onCancel={() => { if (!busy) onClose?.(); }}
    >
      {children}
    </Dialog>,
    document.body,
  );
}

function Dialog({
  title, body, detail, children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  restoreFocus = true,
  onConfirm,
  onCancel,
}) {
  const panelRef = useRef(null);
  const confirmRef = useRef(null);
  const cancelRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const opener = restoreFocus ? document.activeElement : null;
    (tone === "danger" ? cancelRef : confirmRef).current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  }, [tone, restoreFocus]);

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;

    const panel = panelRef.current;
    const buttons = panel ? panel.querySelectorAll("button:not([disabled])") : [];
    if (buttons.length === 0) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    const active = document.activeElement;

    // Focus has landed on the panel itself or fallen outside it: bring it in.
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

  return (
    <div
      className="cf-scrim"
      onKeyDown={onKeyDown}
      onMouseDown={(event) => { downOnBackdrop.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        if (downOnBackdrop.current && event.target === event.currentTarget) onCancel();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        className="cf-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        aria-busy={busy}
        // Focusable, so a click on the dialog's text keeps focus inside it and
        // Escape still works afterwards.
        tabIndex={-1}
      >
        <h2 id={titleId} className="cf-title">{title}</h2>
        <div id={bodyId}>
          {body && <p className="cf-body">{body}</p>}
          {detail && <p className="cf-detail">{detail}</p>}
          {children}
        </div>
        <div className="cf-acts">
          <button
            ref={confirmRef}
            type="button"
            className={`cf-btn cf-btn-${tone}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
          <button
            ref={cancelRef}
            type="button"
            className="cf-cancel"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
