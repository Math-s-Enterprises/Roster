/**
 * Fill in staff email addresses from a spreadsheet they filled in themselves.
 *
 * THE WORKFLOW THIS SERVES
 *
 * A manager sets the shop up from a roster spreadsheet, which per §9 contains
 * no email addresses — so every one of their staff starts with none, and
 * roster dispatch is configured and reaches nobody. Typing twenty-five
 * addresses into a form is miserable, and a typo there fails SILENTLY: the
 * address looks fine and the rota simply never arrives.
 *
 * So: share a sheet, let the staff type their own name and address into it,
 * upload the result here.
 *
 * WHY IT IS TWO STEPS
 *
 * The preview is the whole point. Matching a name to the wrong person emails
 * one member of staff another's working pattern — a data-protection incident
 * rather than a bug — so a human sees every match before anything is written.
 * Ambiguous rows are refused by the server, never guessed, and shown here so
 * they can be fixed in the sheet rather than silently dropped.
 *
 * Nothing is written until Apply, and Apply sends the resolved pairs from the
 * preview rather than the file, so what is saved is exactly what was on
 * screen.
 */
import React, { useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { toast } from "sonner";
import {
  AlertTriangle, Check, FileUp, RefreshCw, Upload, X,
} from "lucide-react";

// Matches the server's statuses. Only `ready` rows are ever written.
const STATUS = {
  ready:     { label: "Will be set",  colour: "var(--primary)" },
  conflict:  { label: "Already set",  colour: "var(--warn)" },
  ambiguous: { label: "Which one?",   colour: "var(--danger)" },
  unknown:   { label: "Not on staff", colour: "var(--ink-mute-2)" },
  duplicate: { label: "Used twice",   colour: "var(--danger)" },
};

export default function ContactImportPanel({ missingCount, total, onDone }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [replace, setReplace] = useState(false);
  const [preview, setPreview] = useState(null);
  const [fileName, setFileName] = useState("");
  const input = useRef(null);

  const upload = async (file, replaceExisting = replace) => {
    if (!file) return;
    setBusy(true);
    setFileName(file.name);
    const body = new FormData();
    body.append("file", file);
    body.append("replace", replaceExisting ? "true" : "false");
    try {
      const r = await api.post("/employees/contacts/preview", body, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(r.data);
    } catch (err) {
      setPreview(null);
      toast.error(errorMessage(err, "Could not read that file"));
    } finally {
      setBusy(false);
    }
  };

  // Re-reading the same file with the opposite setting, rather than filtering
  // what is on screen: whether a row is `ready` is the server's judgement and
  // duplicating that rule here is how the two drift apart.
  const toggleReplace = async (next) => {
    setReplace(next);
    if (input.current?.files?.[0]) await upload(input.current.files[0], next);
  };

  const ready = (preview?.rows || []).filter((r) => r.status === "ready");

  const apply = async () => {
    setBusy(true);
    try {
      const r = await api.post("/employees/contacts/apply", {
        entries: ready.map((x) => ({ employee_id: x.employee_id, email: x.email })),
      });
      toast.success(
        `${r.data.updated} address${r.data.updated === 1 ? "" : "es"} saved`,
      );
      setPreview(null);
      setFileName("");
      if (input.current) input.current.value = "";
      setOpen(false);
      onDone?.();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save those addresses"));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        data-testid="open-contact-import"
        onClick={() => setOpen(true)}
        className="card card-hover w-full p-4 mb-6 flex items-center gap-3 text-left"
      >
        <FileUp size={16} style={{ color: "var(--primary)" }} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px]">Add email addresses from a spreadsheet</div>
          <div className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
            {missingCount > 0
              ? `${missingCount} of ${total} have no address, so they cannot be sent their roster.`
              : "Everyone has an address. Use this to update them in bulk."}
          </div>
        </div>
      </button>
    );
  }

  return (
    <div className="card p-6 mb-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <div className="font-medium flex items-center gap-2">
            <FileUp size={15} style={{ color: "var(--primary)" }} />
            Add email addresses from a spreadsheet
          </div>
          <p className="text-[13px] mt-1" style={{ color: "var(--ink-mute)" }}>
            Share a sheet with two columns — name and email — let your team fill
            it in, then upload it here. Excel or CSV. The headings can say
            anything; rows without an address are ignored.
          </p>
        </div>
        <button onClick={() => { setOpen(false); setPreview(null); }}
                className="btn btn-ghost p-2 shrink-0">
          <X size={15} />
        </button>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <input
          ref={input}
          data-testid="contact-file"
          type="file"
          accept=".csv,.tsv,.xlsx,.xlsm,.xltx"
          onChange={(e) => upload(e.target.files?.[0])}
          className="text-[13px]"
          style={{ maxWidth: 320 }}
        />
        <label className="flex items-center gap-2 text-[12px]"
               style={{ color: "var(--ink-mute)" }}>
          <input
            data-testid="contact-replace"
            type="checkbox"
            checked={replace}
            onChange={(e) => toggleReplace(e.target.checked)}
          />
          Replace addresses that are already set
        </label>
        {busy && <RefreshCw size={14} className="animate-spin" />}
      </div>

      {preview && (
        <div className="mt-5">
          <div className="text-[12px] mb-2" style={{ color: "var(--ink-mute)" }}>
            {fileName} — {preview.rows.length} row(s) with an address.
            {ready.length > 0 && (
              <span style={{ color: "var(--ink)" }}>
                {" "}{ready.length} will be saved.
              </span>
            )}
          </div>

          <div className="card-soft max-h-80 overflow-auto scroll-thin">
            <table className="w-full text-[12px]">
              <tbody>
                {preview.rows.map((row) => {
                  const meta = STATUS[row.status] || STATUS.unknown;
                  return (
                    <tr key={`${row.row}-${row.email}`}
                        style={{ borderBottom: "1px solid var(--hairline-cool)" }}>
                      <td className="px-3 py-2 font-mono"
                          style={{ color: "var(--ink-mute-2)", width: 34 }}>
                        {row.row}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">
                        {row.employee_name || row.name || <em>no name</em>}
                      </td>
                      <td className="px-2 py-2 font-mono truncate"
                          style={{ color: "var(--ink-secondary)", maxWidth: 220 }}>
                        {row.email}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap"
                          style={{ color: meta.colour }}>
                        {meta.label}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Every row that will NOT be written, with the reason, so it can be
              fixed in the sheet rather than quietly lost. */}
          {preview.rows.some((r) => r.status !== "ready") && (
            <div className="mt-3 space-y-1">
              {preview.rows.filter((r) => r.status !== "ready").map((row) => (
                <div key={`why-${row.row}`} className="text-[11px] flex gap-2"
                     style={{ color: "var(--ink-mute)" }}>
                  <AlertTriangle size={11} className="mt-0.5 shrink-0"
                                 style={{ color: STATUS[row.status]?.colour }} />
                  <span>Row {row.row} · {row.name || "no name"} — {row.note}</span>
                </div>
              ))}
            </div>
          )}

          {preview.unmatched_staff?.length > 0 && (
            <div className="text-[11px] mt-3" style={{ color: "var(--ink-mute)" }}>
              Still without an address after this:{" "}
              <span style={{ color: "var(--ink-secondary)" }}>
                {preview.unmatched_staff.join(", ")}
              </span>
            </div>
          )}

          <button
            data-testid="contact-apply"
            onClick={apply}
            disabled={busy || ready.length === 0}
            className="btn btn-primary mt-5"
          >
            <Check size={14} />
            {ready.length === 0
              ? "Nothing to save"
              : `Save ${ready.length} address${ready.length === 1 ? "" : "es"}`}
          </button>
        </div>
      )}
    </div>
  );
}
