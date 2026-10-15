import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "@/styles/notifications.css";
import { MAX_NOTIFICATIONS, formatWhen, useNotifications } from "@/lib/notifications";

/**
 * The Notifications drawer: the last 20 pop-up messages, newest first.
 *
 * Opened from the sidebar, so it is reachable on every screen and in every
 * roster group - the Dashboard only exists for the main group, which would
 * have hidden it from the rest. It is not the Dashboard's Activity feed:
 * that is a permanent record kept on the server of what was done; this is
 * what the screen told you, errors and warnings included, kept in this
 * browser for a short while.
 *
 * Opening it marks everything read, and anything that arrives while it is
 * open is read as it lands, so the sidebar badge never counts what you are
 * looking at.
 *
 * Keyboard: focus moves in on open (to Close, the one control that cannot do
 * damage), Tab stays inside, Escape closes, and focus goes back to whatever
 * opened it. Page scroll is locked while it is open.
 */

const LABEL = { success: "Done", error: "Problem", warning: "Check", info: "Note" };

const fullTime = (at) => new Date(at).toLocaleString([], {
  weekday: "long", day: "numeric", month: "long", year: "numeric",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});

export default function NotificationsDrawer({ onClose }) {
  const { items, markAllRead, clear } = useNotifications();
  const panelRef = useRef(null);
  const closeRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const titleId = useId();
  const [, setTick] = useState(0);

  // Read now, and read again whenever more arrive while this is open.
  useEffect(() => { markAllRead(); }, [items, markAllRead]);

  // "5 min ago" would go stale while the drawer sits open.
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const opener = document.activeElement;
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
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
    const buttons = panel ? panel.querySelectorAll("button:not([disabled])") : [];
    if (buttons.length === 0) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
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
      className="nt-scrim"
      onKeyDown={onKeyDown}
      onMouseDown={(event) => { downOnBackdrop.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        if (downOnBackdrop.current && event.target === event.currentTarget) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <aside
        ref={panelRef}
        className="nt-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="nt-head">
          <div>
            <h2 id={titleId} className="nt-title">
              Notifications <span>({items.length})</span>
            </h2>
            <p className="nt-sub">
              The last {MAX_NOTIFICATIONS} messages that popped up while you worked, newest first.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="nt-close"
            data-testid="btn-close-notifications"
            onClick={onClose}
          >
            Close
          </button>
        </header>

        <div className="nt-toolbar">
          <button
            type="button"
            className="nt-link"
            data-testid="btn-clear-notifications"
            disabled={items.length === 0}
            onClick={clear}
          >
            Clear all
          </button>
        </div>

        {items.length === 0 ? (
          <p className="nt-empty">
            Nothing yet. Messages that pop up while you work are kept here.
          </p>
        ) : (
          <ol className="nt-list" aria-label="Recent notifications">
            {items.map((item) => (
              <li className="nt-item" key={item.id}>
                <div className="nt-meta">
                  <span className="nt-kind" data-kind={item.kind}>{LABEL[item.kind]}</span>
                  <time dateTime={new Date(item.at).toISOString()} title={fullTime(item.at)}>
                    {formatWhen(item.at)}
                  </time>
                </div>
                <div className="nt-msg">{item.message}</div>
                {item.description && <div className="nt-desc">{item.description}</div>}
              </li>
            ))}
          </ol>
        )}

        <footer className="nt-foot">
          Only the latest {MAX_NOTIFICATIONS} are kept - the oldest makes room as new ones arrive.
          They stay on this device, for your account only, until you clear them.
        </footer>
      </aside>
    </div>,
    document.body,
  );
}
