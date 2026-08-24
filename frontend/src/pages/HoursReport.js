import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Download, FileDown, Loader2 } from "lucide-react";

import { api, errorMessage, fmtHours, fmtMoney } from "@/lib/api";

/**
 * Hours and wages for a period.
 *
 * The paid/unpaid break distinction is the whole point of the page, so the
 * shop's setting is stated at the top rather than left for the reader to
 * infer from a column that may or may not be zero.
 */

const iso = (d) => d.toISOString().slice(0, 10);

/** Monday of the week containing `d`. Weeks run Mon–Sun everywhere else. */
function mondayOf(d) {
  const out = new Date(d);
  out.setDate(out.getDate() - ((out.getDay() + 6) % 7));
  return out;
}

function presetRange(key) {
  const today = new Date();
  if (key === "this-week") {
    const from = mondayOf(today);
    const to = new Date(from); to.setDate(to.getDate() + 6);
    return [iso(from), iso(to)];
  }
  if (key === "last-week") {
    const from = mondayOf(today); from.setDate(from.getDate() - 7);
    const to = new Date(from); to.setDate(to.getDate() + 6);
    return [iso(from), iso(to)];
  }
  if (key === "this-month") {
    const from = new Date(today.getFullYear(), today.getMonth(), 1);
    const to = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return [iso(from), iso(to)];
  }
  // last-month
  const from = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const to = new Date(today.getFullYear(), today.getMonth(), 0);
  return [iso(from), iso(to)];
}

const PRESETS = [
  ["this-week", "This week"],
  ["last-week", "Last week"],
  ["this-month", "This month"],
  ["last-month", "Last month"],
];

export default function HoursReport() {
  const [preset, setPreset] = useState("last-month");
  const [[start, end], setRange] = useState(() => presetRange("last-month"));
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const choose = (key) => { setPreset(key); setRange(presetRange(key)); };

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const { data } = await api.get("/reports/hours", { params: { start, end } });
      setData(data);
    } catch (err) {
      toast.error(errorMessage(err, "Could not build the report"));
      setData(null);
    } finally { setBusy(false); }
  }, [start, end]);

  useEffect(() => { load(); }, [load]);

  const unpaidBreaks = data && !data.breaks_are_paid;

  const columns = useMemo(() => {
    // The break column only exists when breaks are unpaid. A column of
    // zeroes invites the reader to wonder whether it is broken.
    const base = [
      ["name", "Employee"],
      ["role", "Role"],
      ["days_worked", "Days"],
      ["span_hours", "Hours on floor"],
    ];
    if (unpaidBreaks) base.push(["break_hours", "Breaks"]);
    base.push(["paid_hours", "Paid hours"]);
    base.push(["paid_holiday_hours", "Paid holiday"]);
    base.push(["sick_days", "Sick"]);
    base.push(["cost", "Cost"]);
    return base;
  }, [unpaidBreaks]);

  const exportCsv = () => {
    if (!data?.rows?.length) return;
    const header = columns.map(([, label]) => label);
    const lines = [header.join(",")];
    for (const row of data.rows) {
      lines.push(columns.map(([key]) => {
        const v = row[key];
        return typeof v === "string" && v.includes(",") ? `"${v}"` : v;
      }).join(","));
    }
    // A totals row, because the first thing anyone does with this file is
    // add up a column and check it against the app.
    lines.push(columns.map(([key]) =>
      key === "name" ? "TOTAL" : (data.totals[key] ?? "")
    ).join(","));

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `hours-${data.start}-to-${data.end}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="eyebrow mb-2">Reports</div>
        <h1 className="display">Hours and wages</h1>
        <p className="mt-2 text-sm max-w-2xl" style={{ color: "var(--ink-mute)" }}>
          Built from approved rosters only. A draft is a proposal, so counting
          one would bill for hours nobody was told to work.
        </p>
      </div>

      <div className="card p-5 mb-6">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex gap-1 flex-wrap">
            {PRESETS.map(([key, label]) => (
              <button
                key={key}
                data-testid={`period-${key}`}
                onClick={() => choose(key)}
                className={preset === key ? "btn btn-primary" : "btn btn-secondary"}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="flex items-end gap-2 ml-auto">
            <label className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
              From
              <input
                type="date" value={start}
                onChange={(e) => { setPreset(""); setRange([e.target.value, end]); }}
                className="block px-3 py-2 font-mono text-sm mt-1"
              />
            </label>
            <label className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
              To
              <input
                type="date" value={end}
                onChange={(e) => { setPreset(""); setRange([start, e.target.value]); }}
                className="block px-3 py-2 font-mono text-sm mt-1"
              />
            </label>
          </div>
        </div>

        {data && (
          <div className="mt-4 pt-4 text-[12px] flex items-center gap-2 flex-wrap"
               style={{ borderTop: "1px solid var(--hairline)", color: "var(--ink-mute)" }}>
            <span className={`pill ${unpaidBreaks ? "" : "pill-warn"}`}>
              {unpaidBreaks ? "Breaks unpaid" : "Breaks paid"}
            </span>
            {unpaidBreaks
              ? "Paid hours exclude breaks. Change this in shop settings if your staff are paid through them."
              : "Every hour on the floor is paid, breaks included."}
          </div>
        )}
      </div>

      {busy && !data ? (
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--ink-mute)" }}>
          <Loader2 size={15} className="animate-spin" /> Building the report…
        </div>
      ) : !data?.rows?.length ? (
        <div className="card p-8 text-center text-sm" style={{ color: "var(--ink-mute)" }}>
          Nothing approved in this period.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-px rounded-lg overflow-hidden mb-6"
               style={{ background: "var(--hairline)" }}>
            <Metric label="People" value={data.totals.people} />
            <Metric label="Paid hours" value={fmtHours(data.totals.paid_hours)} />
            {unpaidBreaks && <Metric label="Unpaid breaks" value={fmtHours(data.totals.break_hours)} />}
            <Metric label="Wage cost" value={fmtMoney(data.totals.cost)} />
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--hairline)" }}>
                  {columns.map(([key, label]) => (
                    <th key={key}
                        className={`px-3 py-2.5 font-medium ${key === "name" || key === "role" ? "text-left" : "text-right"}`}
                        style={{ color: "var(--ink-mute-2)" }}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.employee_id}
                      data-testid={`hours-row-${row.employee_id}`}
                      style={{ borderBottom: "1px solid var(--hairline)" }}>
                    <td className="px-3 py-2.5">
                      {row.name}
                      {row.short_weeks?.length > 0 && (
                        <span
                          className="ml-2 inline-flex items-center gap-1 text-[11px]"
                          style={{ color: "var(--warn)" }}
                          title={`Under contract in: ${row.short_weeks.join(", ")}`}
                        >
                          <AlertTriangle size={11} />
                          {row.short_weeks.length} short week{row.short_weeks.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5" style={{ color: "var(--ink-mute-2)" }}>{row.role}</td>
                    <td className="px-3 py-2.5 text-right font-mono">{row.days_worked}</td>
                    <td className="px-3 py-2.5 text-right font-mono">{fmtHours(row.span_hours)}</td>
                    {unpaidBreaks && (
                      <td className="px-3 py-2.5 text-right font-mono" style={{ color: "var(--ink-mute-2)" }}>
                        {fmtHours(row.break_hours)}
                      </td>
                    )}
                    <td className="px-3 py-2.5 text-right font-mono">{fmtHours(row.paid_hours)}</td>
                    <td className="px-3 py-2.5 text-right font-mono" style={{ color: "var(--ink-mute-2)" }}>
                      {row.paid_holiday_days ? fmtHours(row.paid_holiday_hours) : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono" style={{ color: "var(--ink-mute-2)" }}>
                      {row.sick_days || "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono">{fmtMoney(row.cost)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: "var(--canvas-soft)" }}>
                  <td className="px-3 py-2.5 font-medium" colSpan={2}>Total</td>
                  <td className="px-3 py-2.5 text-right font-mono">{data.totals.days_worked}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{fmtHours(data.totals.span_hours)}</td>
                  {unpaidBreaks && (
                    <td className="px-3 py-2.5 text-right font-mono">{fmtHours(data.totals.break_hours)}</td>
                  )}
                  <td className="px-3 py-2.5 text-right font-mono">{fmtHours(data.totals.paid_hours)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{fmtHours(data.totals.paid_holiday_hours)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{data.totals.sick_days || "—"}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{fmtMoney(data.totals.cost)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="flex items-center gap-2 mt-4 flex-wrap">
            <button data-testid="btn-export-csv" onClick={exportCsv} className="btn btn-secondary">
              <Download size={14} /> Export CSV
            </button>
            <button onClick={() => window.print()} className="btn btn-secondary">
              <FileDown size={14} /> Print
            </button>
            <span className="text-[11px] ml-auto" style={{ color: "var(--ink-mute-2)" }}>
              {data.whole_weeks?.length || 0} whole week(s) in this period counted
              towards contract checks.
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="p-3" style={{ background: "var(--canvas-soft)" }}>
      <div className="eyebrow">{label}</div>
      <div className="mt-1 text-[22px] font-mono leading-none">{value}</div>
    </div>
  );
}
