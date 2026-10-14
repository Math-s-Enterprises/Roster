/**
 * Delete your own account, and everything in it.
 *
 * IT CANNOT BE UNDONE, so the button is hard to press by accident and impossible to press
 * for somebody else:
 *
 *   - The email address has to be typed out. A mis-click or a slip of the Enter key cannot
 *     do that; it also makes the person read which account this is.
 *   - Then proof of who is typing. The password, for an account that has one. An account
 *     that signs in with Google has no password, so it confirms with a fresh Google
 *     sign-in instead - the same check the server makes against the same Google account.
 *     Being signed in only proves a browser session exists, not that the person at the
 *     keyboard owns the account (the same reasoning as Change password).
 *   - The button stays off until both are done, and while it is working nothing can close
 *     the dialog, so it cannot be abandoned half way by a stray click.
 *
 * WHEN IT WORKS, this browser is cleaned as well. The server has erased the account, but
 * this browser still holds the sign-in token, the last 20 notifications (which name staff)
 * and a count of wrong passwords for this email. "Everything" includes those, so they go
 * too, and the person is signed out and taken to the sign-in page.
 *
 * WHEN IT FAILS, nothing has been deleted - the server cancels billing first and stops if it
 * cannot - and the message it sends says so. The dialog stays open and the password is
 * cleared, so it can be tried again.
 *
 * It is a portal for the same reason Change password is: it is opened from the sidebar, and
 * a fixed-position element inside a transformed parent is positioned against that parent,
 * not the screen.
 */
import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { RefreshCw, Trash2, X } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import GoogleSignInButton from "@/components/GoogleSignInButton";
import { clearGuard } from "@/lib/loginGuard";

// Where lib/notifications.js keeps each person's list. Kept in step by hand; a test checks
// that it still matches, so renaming one without the other fails loudly instead of leaving
// somebody's staff names behind in the browser of a deleted account.
export const NOTIFICATIONS_KEY_PREFIX = "roster_notifications:";

/** Everything this browser still holds that belongs to the account that was just deleted. */
export function eraseBrowserTraces(user) {
  for (const store of [() => localStorage, () => sessionStorage]) {
    try {
      store().removeItem(`${NOTIFICATIONS_KEY_PREFIX}${user.user_id}`);
    } catch {
      /* storage blocked: there is nothing stored to remove */
    }
  }
  clearGuard(user.email);
}

const ERASED = [
  "Your shop settings, roster groups, roles and opening hours",
  "Every employee and their details, holiday balances and sick leave",
  "Every roster, including past weeks, and all fixed shifts",
  "Your AI rules, imported history and activity log",
  "Your sign-in: you will be signed out on every device",
];

export default function DeleteAccountModal({ onClose }) {
  const { user, providers, logout } = useAuth();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [credential, setCredential] = useState("");
  const [deleting, setDeleting] = useState(false);
  // Bumped after a refusal, to put the cursor back in the password box once it is enabled
  // again. It cannot be done in the same breath as re-enabling it: a disabled box cannot
  // take focus, and the screen has not redrawn yet.
  const [retry, setRetry] = useState(0);
  const panelRef = useRef(null);
  const emailRef = useRef(null);
  const passwordRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const titleId = useId();
  const bodyId = useId();

  // An account marked as having no password signs in with Google only. Anything else,
  // including an older server that does not say, is asked for a password.
  const hasPassword = user?.has_password !== false;
  const googleAvailable = Boolean(providers?.google && providers?.google_client_id);

  const emailMatches = typed.trim() !== ""
    && typed.trim().toLowerCase() === (user?.email || "").trim().toLowerCase();
  const proven = hasPassword ? password.length > 0 : Boolean(credential);
  const ready = emailMatches && proven && !deleting;

  // Held in refs so the key handler below can stay registered once and still see the latest.
  const deletingRef = useRef(deleting);
  deletingRef.current = deleting;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement;
    emailRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!deletingRef.current) closeRef.current?.();     // not while it is working
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      const stops = panel
        ? [...panel.querySelectorAll("button:not([disabled]), input:not([disabled]), a[href]")]
        : [];
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!panel.contains(active)) {
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
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  }, []);

  useEffect(() => {
    if (retry) passwordRef.current?.focus();
  }, [retry]);

  const submit = async () => {
    if (!ready) return;
    setDeleting(true);
    try {
      await api.post("/auth/delete-account", {
        confirm_email: typed.trim(),
        ...(hasPassword ? { password } : { google_credential: credential }),
      });
    } catch (err) {
      // Nothing was deleted. Say why, and let them try again with the secret cleared.
      toast.error(errorMessage(err, "Could not delete the account"));
      setPassword("");
      setCredential("");
      setDeleting(false);
      if (hasPassword) setRetry((n) => n + 1);
      return;
    }
    // Gone on the server. Leave nothing behind in this browser either, then sign out.
    eraseBrowserTraces(user);
    toast.success("Your account and all its data have been deleted.");
    await logout();
    navigate("/login", { replace: true });
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onMouseDown={(event) => { downOnBackdrop.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        if (downOnBackdrop.current && event.target === event.currentTarget && !deleting) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        data-testid="delete-account-dialog"
        className="max-w-md w-full card elevated p-8 relative"
        style={{ maxHeight: "92vh", overflowY: "auto" }}
      >
        <button
          type="button"
          onClick={onClose}
          disabled={deleting}
          aria-label="Close"
          className="btn btn-ghost absolute top-3 right-3 p-2"
        >
          <X size={16} />
        </button>

        <h2 id={titleId} className="font-medium flex items-center gap-2 mb-2" style={{ color: "var(--danger)" }}>
          <Trash2 size={15} /> Delete your account
        </h2>

        <div id={bodyId}>
          <p className="text-[13px] mb-3" style={{ color: "var(--ink)" }}>
            <strong>This permanently erases everything in this account, and it cannot be undone.</strong>
          </p>
          <ul className="text-[13px] mb-3 space-y-1 list-disc pl-5" style={{ color: "var(--ink-mute)" }} data-testid="delete-account-erased">
            {ERASED.map((line) => <li key={line}>{line}</li>)}
            <li>Any subscription is cancelled first, so you are not charged again</li>
          </ul>
          <p className="text-[12px] mb-5" style={{ color: "var(--ink-mute)" }}>
            Want to keep anything? Download it first: the Employees page and every roster have
            export options. Once you press Delete, nobody can get it back, including us. You can
            sign up again later with the same email; that account starts completely empty.
          </p>
        </div>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            Type your email address to confirm
          </div>
          <input
            ref={emailRef}
            data-testid="delete-account-email"
            type="text"
            inputMode="email"
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={user?.email}
            disabled={deleting}
            className="w-full px-3 py-2 text-[13px]"
          />
        </label>

        {hasPassword ? (
          <label className="block mb-1">
            <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>Your password</div>
            <input
              ref={passwordRef}
              data-testid="delete-account-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              disabled={deleting}
              className="w-full px-3 py-2 text-[13px]"
            />
          </label>
        ) : (
          <div className="mb-1" data-testid="delete-account-google">
            <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
              You signed up with Google, so confirm it is you with Google
            </div>
            {credential ? (
              <div role="status" className="text-[13px]" style={{ color: "var(--ink)" }}>
                Confirmed with Google.
              </div>
            ) : googleAvailable ? (
              <GoogleSignInButton
                clientId={providers.google_client_id}
                onCredential={setCredential}
                disabled={!emailMatches || deleting}
              />
            ) : (
              <div className="text-[12px]" style={{ color: "var(--warn)" }}>
                Google sign-in is not available right now, so this account cannot be deleted
                from here. Please try again later.
              </div>
            )}
            {!credential && googleAvailable && !emailMatches && (
              <div className="text-[11px] mt-1" style={{ color: "var(--ink-mute)" }}>
                Type your email address above first.
              </div>
            )}
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            type="button"
            data-testid="delete-account-cancel"
            onClick={onClose}
            disabled={deleting}
            className="btn flex-1"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="delete-account-confirm"
            onClick={submit}
            disabled={!ready}
            className="btn btn-danger flex-1 font-medium"
          >
            {deleting ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {deleting ? "Deleting…" : "Delete everything"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
