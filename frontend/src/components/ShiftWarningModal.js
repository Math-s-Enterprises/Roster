import React from "react";
import { AlertTriangle, X } from "lucide-react";

export default function ShiftWarningModal({
  warnings, confirmLabel, onClose, onConfirm,
  title = "Confirm this shift?",
  description = "This shift conflicts with information recorded for the employee.",
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4"
         onClick={(event) => { event.stopPropagation(); onClose(); }}>
      <div className="max-w-md w-full card elevated p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={18} style={{ color: "var(--warn)" }} />
          <h2>{title}</h2>
        </div>
        <p className="text-[13px] mb-4" style={{ color: "var(--ink-mute)" }}>
          {description}
        </p>
        <div className="card-soft p-4 text-[13px] space-y-2" style={{ color: "var(--ink-secondary)" }}>
          {warnings.map((warning) => <p key={warning}>{warning}</p>)}
        </div>
        <div className="flex gap-2 mt-5">
          <button type="button" onClick={onClose} className="btn btn-secondary flex-1">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} className="btn btn-primary flex-1">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
