import React, { useState } from "react";
import * as AlertDialog from "@radix-ui/react-alert-dialog";

export default function ConfirmDialog({ title, description, onClose, onConfirm,
  confirmLabel = "Remove", children, busy: externalBusy = false }) {
  const [saving, setBusy] = useState(false);
  const busy = saving || externalBusy;
  const confirm = async () => {
    setBusy(true);
    try {
      if (await onConfirm() !== false) onClose();
    } finally { setBusy(false); }
  };
  return (
    <AlertDialog.Root open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm" />
        <AlertDialog.Content className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(100%-2rem)] max-w-md card elevated p-6">
          <AlertDialog.Title className="text-lg font-semibold mb-2">{title}</AlertDialog.Title>
          <AlertDialog.Description className="text-sm ui-muted mb-6">{description}</AlertDialog.Description>
          {children}
          <div className="flex justify-between gap-3">
            <AlertDialog.Cancel disabled={busy} className="btn btn-secondary">Cancel</AlertDialog.Cancel>
            <button type="button" disabled={busy} className="btn btn-danger" onClick={confirm}>
              {busy ? "Saving…" : confirmLabel}
            </button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
