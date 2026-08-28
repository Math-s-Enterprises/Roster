/**
 * Change your own password.
 *
 * WHY THE CURRENT PASSWORD IS ASKED FOR
 *
 * You are already signed in, so this looks redundant. It is not. Being signed
 * in proves a browser session exists; it does not prove the person at the
 * keyboard is the account holder. Without it, anybody who walks past an
 * unlocked laptop in the back office can lock the owner out of their own
 * roster permanently.
 *
 * Same reasoning as force approval asking for it before a week with breaches
 * goes through.
 *
 * WHY IT SAYS OTHER DEVICES WILL BE SIGNED OUT
 *
 * Because they will, and somebody halfway through something on their phone
 * should find that out before pressing the button rather than after.
 *
 * WHY IT IS A PORTAL
 *
 * It is opened from a button inside the sidebar, and rendering it there put
 * it INSIDE the sidebar's DOM. A `position: fixed` element is positioned
 * against the viewport only while no ancestor creates a containing block —
 * any transform, filter or backdrop-filter on a parent makes it position
 * against THAT instead. The sidebar has one, so the dialog was squeezed into
 * the left column instead of sitting over the page.
 *
 * Rendering into document.body means the dialog does not care where it was
 * opened from. Fixing it with z-index or width would only have papered over
 * the wrong parent.
 */
import React, { useState } from "react";
import { createPortal } from "react-dom";
import { api, errorMessage, setToken } from "@/lib/api";
import { toast } from "sonner";
import { X, KeyRound, RefreshCw } from "lucide-react";

const MIN_LENGTH = 8;

export default function ChangePasswordModal({ onClose }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  // Checked here only to say so before the round trip. The server checks all
  // of it again — this is a courtesy, not the rule.
  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const mismatch = confirm.length > 0 && next !== confirm;
  const unchanged = next.length > 0 && next === current;
  const ready = current && next.length >= MIN_LENGTH && next === confirm && !unchanged;

  const submit = async () => {
    if (!ready) return;
    setSaving(true);
    try {
      const response = await api.post("/auth/change-password", {
        current_password: current, new_password: next,
      });
      // The server hands back a token stamped with the new version. Without
      // storing it, the very next request from THIS tab would 401 — you would
      // sign yourself out by changing your own password.
      if (response.data?.token) setToken(response.data.token);
      toast.success("Password changed. Other devices have been signed out.");
      onClose();
    } catch (err) {
      toast.error(errorMessage(err, "Could not change your password"));
    } finally { setSaving(false); }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="max-w-sm w-full card elevated p-8 relative"
           onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>

        <div className="font-medium flex items-center gap-2 mb-1">
          <KeyRound size={15} /> Change password
        </div>
        <div className="text-[13px] mb-5" style={{ color: "var(--ink-mute)" }}>
          You will stay signed in here. Every other device will be signed out.
        </div>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            Current password
          </div>
          <input
            data-testid="current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoFocus
            className="w-full px-3 py-2 text-[13px]"
          />
        </label>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            New password
          </div>
          <input
            data-testid="new-password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className="w-full px-3 py-2 text-[13px]"
          />
          {tooShort && (
            <div className="text-[11px] mt-1" style={{ color: "var(--warn)" }}>
              At least {MIN_LENGTH} characters.
            </div>
          )}
          {unchanged && (
            <div className="text-[11px] mt-1" style={{ color: "var(--warn)" }}>
              That is the password you already have.
            </div>
          )}
        </label>

        <label className="block">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            New password again
          </div>
          <input
            data-testid="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="w-full px-3 py-2 text-[13px]"
          />
          {mismatch && (
            <div className="text-[11px] mt-1" style={{ color: "var(--warn)" }}>
              These do not match.
            </div>
          )}
        </label>

        <button
          data-testid="change-password-save"
          onClick={submit}
          disabled={!ready || saving}
          className="btn btn-primary w-full mt-5"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <KeyRound size={14} />}
          Change password
        </button>
      </div>
    </div>,
    document.body,
  );
}
