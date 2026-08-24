import React, { useEffect, useMemo, useState } from "react";
import { api, errorMessage, DAYS, DAY_SHORT, mondayOf } from "@/lib/api";
import { toast } from "sonner";
import { CalendarPlus, Trash2 } from "lucide-react";

export default function CalendarPage() {
  const [hols, setHols] = useState([]);
  const [emps, setEmps] = useState([]);
  const [date, setDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState("shop");
  const scopeOpts = [
    { k: "shop", l: "Shop closed" },
    { k: "leave-week", l: "Employee leave" },
    { k: "sick", l: "Sick" },
  ];
  const [empId, setEmpId] = useState("");

  // Employee-leave mode: a from/to range. Days are grouped into weeks purely
  // for display — the booking itself is a set of dates, so two days off does
  // not drag the rest of the week into it.
  const [leaveFrom, setLeaveFrom] = useState("");
  const [leaveTo, setLeaveTo] = useState("");
  const [paidDates, setPaidDates] = useState([]);

  const iso = (d) => {
    const m = `${d.getMonth() + 1}`.padStart(2, "0");
    const day = `${d.getDate()}`.padStart(2, "0");
    return `${d.getFullYear()}-${m}-${day}`;
  };

  /** Every date in the range, bucketed by the Monday of its week. */
  const leaveWeeks = useMemo(() => {
    if (!leaveFrom || !leaveTo || leaveTo < leaveFrom) return [];
    const buckets = new Map();
    const cursor = new Date(`${leaveFrom}T00:00:00`);
    const last = new Date(`${leaveTo}T00:00:00`);
    while (cursor <= last) {
      const week = mondayOf(iso(cursor));
      if (!buckets.has(week)) buckets.set(week, []);
      buckets.get(week).push(iso(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    return [...buckets.entries()].map(([week, dates]) => ({ week, dates }));
  }, [leaveFrom, leaveTo]);

  const allLeaveDates = useMemo(
    () => leaveWeeks.flatMap((w) => w.dates), [leaveWeeks],
  );

  // Ticks are dropped if the range shrinks past them, so the payload can
  // never contain a paid date outside the booking.
  useEffect(() => {
    setPaidDates((prev) => prev.filter((d) => allLeaveDates.includes(d)));
  }, [allLeaveDates]);

  const totalPaidDays = paidDates.length;

  const selectedEmployee = useMemo(
    () => emps.find((e) => e.employee_id === empId),
    [emps, empId],
  );

  // Holiday pay is a normal day's pay, so default to their contract spread
  // over five days rather than a flat 8 hours.
  const hoursPerDay = selectedEmployee?.max_weekly_hours
    ? Math.round((selectedEmployee.max_weekly_hours / 5) * 100) / 100
    : null;

  // What this employee actually has left. Fetched rather than derived on the
  // client because the balance depends on every approved roster ever — and
  // because the server is the thing that will refuse the booking, so the
  // number shown here must be the number it decides on.
  const [balance, setBalance] = useState(null);
  // Bumped after a booking so the panel reflects what was just spent.
  const [balanceVersion, setBalanceVersion] = useState(0);
  useEffect(() => {
    if (!empId || scope !== "leave-week") { setBalance(null); return; }
    let cancelled = false;
    const params = hoursPerDay ? `?hours_per_day=${hoursPerDay}` : "";
    api.get(`/holiday-balance/${empId}${params}`)
      .then((r) => { if (!cancelled) setBalance(r.data); })
      .catch(() => { if (!cancelled) setBalance(null); });
    return () => { cancelled = true; };
  }, [empId, scope, hoursPerDay, balanceVersion]);

  const maxPaidDays = balance?.max_payable_days ?? null;
  const requestedHours = hoursPerDay
    ? Math.round(totalPaidDays * hoursPerDay * 100) / 100 : null;
  const overBalance =
    balance != null && requestedHours != null &&
    requestedHours > balance.available_hours + 1e-6;

  const load = async () => {
    const [h, e] = await Promise.all([api.get("/holidays"), api.get("/employees")]);
    const today = new Date().toISOString().slice(0, 10);
    const withStatus = h.data.map((x) => {
      const end = x.end_date || x.date;
      const status = end < today ? "past" : (x.date > today ? "upcoming" : "current");
      return { ...x, _status: status };
    });
    setHols(withStatus.sort((a, b) => b.date.localeCompare(a.date)));
    setEmps(e.data);
  };
  useEffect(() => { load(); }, []);

  // Stopped at the cap rather than letting the manager tick freely and be
  // refused on submit — by then they have usually already told the employee.
  const toggleDate = (date) =>
    setPaidDates((prev) => {
      if (prev.includes(date)) return prev.filter((x) => x !== date);
      if (maxPaidDays != null && prev.length >= maxPaidDays) {
        toast.error(
          `${selectedEmployee?.name || "This employee"} has ${balance.available_hours}h left, ` +
          `which covers ${maxPaidDays} paid day${maxPaidDays === 1 ? "" : "s"}. ` +
          "The remaining days can still be booked as unpaid.",
        );
        return prev;
      }
      return [...prev, date];
    });

  /** Most bookings mean "all my normal working days", so offer that in one click. */
  const toggleAll = () => {
    if (paidDates.length === allLeaveDates.length) { setPaidDates([]); return; }
    // "All paid" still has to respect the balance, so it fills up to the cap.
    const limit = maxPaidDays == null
      ? allLeaveDates.length : Math.min(maxPaidDays, allLeaveDates.length);
    if (limit < allLeaveDates.length) {
      toast.warning(
        `Only ${limit} of ${allLeaveDates.length} day(s) fit in the remaining ` +
        `${balance.available_hours}h. The rest are booked as unpaid.`,
      );
    }
    setPaidDates(allLeaveDates.slice(0, limit));
  };

  const add = async (e) => {
    e.preventDefault();
    try {
      if (scope === "leave-week") {
        const r = await api.post("/holidays/leave", {
          employee_id: empId,
          start_date: leaveFrom,
          end_date: leaveTo,
          paid_dates: paidDates,
          label: label || "Holiday",
        });
        toast.success(
          `${r.data.employee}: ${r.data.paid_days} paid day(s) = ${r.data.paid_hours_total}h` +
            (r.data.unpaid_days ? `, ${r.data.unpaid_days} unpaid` : ""),
        );
        setPaidDates([]); setLabel("");
        setBalanceVersion((v) => v + 1);
      } else {
        await api.post("/holidays", {
          date,
          end_date: endDate || null,
          label,
          scope,
          employee_id: scope === "sick" ? empId : null,
        });
        setDate(""); setEndDate(""); setLabel(""); setEmpId("");
        toast.success("Added");
      }
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save"));
    }
  };

  const del = async (id) => {
    await api.delete(`/holidays/${id}`); toast.success("Removed"); load();
  };

  const empName = (id) => emps.find((e) => e.employee_id === id)?.name || "—";

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Calendar</div>
        <h1 className="text-4xl font-light">Holidays & off-days</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form onSubmit={add} className="glass rounded-2xl p-6 space-y-4">
          <h2 className="font-medium">Add leave</h2>

          <div>
            <label className="text-xs text-white/60">Type</label>
            <div className="flex gap-2 mt-1">
              {scopeOpts.map((o) => (
                <button
                  type="button"
                  key={o.k}
                  onClick={() => setScope(o.k)}
                  className={`flex-1 px-2 py-2 rounded-lg text-[11px] ${scope === o.k ? "neon-btn" : "glass-solid text-white/60"}`}
                >
                  {o.l}
                </button>
              ))}
            </div>
            {scope === "sick" && (
              <div className="text-[10px] text-amber-400 mt-2">
                Sick leave is never used as AI training data.
              </div>
            )}
          </div>

          {scope !== "shop" && (
            <div>
              <label className="text-xs text-white/60">Employee</label>
              <select
                required
                value={empId}
                onChange={(e) => setEmpId(e.target.value)}
                className="mt-1 w-full px-3 py-2.5 rounded-lg"
              >
                <option value="">Select…</option>
                {emps.map((e) => (
                  <option key={e.employee_id} value={e.employee_id}>
                    {e.name} · {e.max_weekly_hours}h
                  </option>
                ))}
              </select>
            </div>
          )}

          {scope === "leave-week" && balance && (
            <div className="glass-solid rounded-xl p-3 space-y-1 text-[11px]">
              <div className="flex justify-between">
                <span className="text-white/50">Holiday available</span>
                <span className="font-mono text-cyan-400">{balance.available_hours}h</span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/50">Covers</span>
                <span className="font-mono text-white/80">
                  {balance.max_payable_days} day{balance.max_payable_days === 1 ? "" : "s"}
                  <span className="text-white/40"> @ {balance.hours_per_day}h</span>
                </span>
              </div>
              <div className="text-white/30 pt-1 border-t border-white/5">
                {balance.opening_hours}h carried in + {balance.accrued_hours}h earned
                {balance.adjustment_hours ? ` ${balance.adjustment_hours > 0 ? "+" : "−"} ${Math.abs(balance.adjustment_hours)}h adjusted` : ""}
                {" − "}{balance.used_hours}h taken
              </div>
            </div>
          )}

          {scope === "leave-week" ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-white/60">From</label>
                  <input
                    data-testid="leave-from"
                    required
                    type="date"
                    value={leaveFrom}
                    onChange={(e) => {
                      setLeaveFrom(e.target.value);
                      if (!leaveTo || leaveTo < e.target.value) setLeaveTo(e.target.value);
                    }}
                    className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs text-white/60">To</label>
                  <input
                    data-testid="leave-to"
                    required
                    type="date"
                    min={leaveFrom}
                    value={leaveTo}
                    onChange={(e) => setLeaveTo(e.target.value)}
                    className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono"
                  />
                </div>
              </div>

              {allLeaveDates.length > 0 && (
                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-xs text-white/60">
                      Which days are paid? ({allLeaveDates.length} day
                      {allLeaveDates.length === 1 ? "" : "s"} off)
                    </label>
                    <button
                      type="button"
                      onClick={toggleAll}
                      className="text-[10px] px-2 py-1 rounded-full glass-solid text-white/60 hover:text-white"
                    >
                      {paidDates.length === allLeaveDates.length ? "Clear all" : "All paid"}
                    </button>
                  </div>

                  {/* Grouped by week only so a long booking stays readable.
                      Days outside the range are shown greyed and inert —
                      those are normal working days and must not be touched. */}
                  <div className="mt-2 space-y-2 max-h-64 overflow-y-auto scroll-thin">
                    {leaveWeeks.map(({ week, dates }, i) => {
                      const paidHere = dates.filter((d) => paidDates.includes(d)).length;
                      return (
                        <div key={week} className="glass-solid rounded-lg p-2">
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-[11px] text-white/70">
                              Week {i + 1}
                              <span className="text-white/40 font-mono ml-2">{week}</span>
                            </span>
                            <span className="text-[10px] text-cyan-400">
                              {paidHere ? `${paidHere} paid` : "none paid"}
                            </span>
                          </div>
                          <div className="flex gap-1">
                            {DAYS.map((dayKey, dayIndex) => {
                              const d = new Date(`${week}T00:00:00`);
                              d.setDate(d.getDate() + dayIndex);
                              const date = iso(d);
                              const inRange = dates.includes(date);
                              const on = paidDates.includes(date);
                              return (
                                <button
                                  type="button"
                                  key={date}
                                  disabled={!inRange}
                                  onClick={() => toggleDate(date)}
                                  title={inRange ? date : `${date} — not in this booking`}
                                  className={`flex-1 py-1.5 rounded text-[10px] ${
                                    !inRange
                                      ? "bg-transparent text-white/15 cursor-default"
                                      : on
                                        ? "neon-btn"
                                        : "bg-white/5 text-white/40"
                                  }`}
                                >
                                  {DAY_SHORT[dayKey]}
                                  <span className="block text-[8px] opacity-60">
                                    {date.slice(8)}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <p className="text-[11px] text-white/50 mt-2 leading-relaxed">
                    {totalPaidDays === 0 ? (
                      "Tick the days they'd normally have worked — the rest are unpaid."
                    ) : (
                      <>
                        <span className={overBalance ? "text-red-400" : "text-cyan-400"}>
                          {totalPaidDays} paid day{totalPaidDays > 1 ? "s" : ""}
                        </span>
                        {requestedHours != null ? ` × ${hoursPerDay}h = ${requestedHours}h` : ""}
                        {allLeaveDates.length - totalPaidDays > 0 && (
                          <> · {allLeaveDates.length - totalPaidDays} unpaid</>
                        )}
                        . Days outside this range are unaffected.
                      </>
                    )}
                  </p>

                  {overBalance && (
                    <p className="text-[11px] text-red-400 mt-1.5">
                      That is {Math.round((requestedHours - balance.available_hours) * 100) / 100}h
                      more than they have left. Untick a day or book it as unpaid.
                    </p>
                  )}
                </div>
              )}

              <div>
                <label className="text-xs text-white/60">Label</label>
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Holiday"
                  className="mt-1 w-full px-3 py-2.5 rounded-lg"
                />
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-white/60">Start date</label>
                  <input data-testid="hol-date" required type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
                </div>
                <div>
                  <label className="text-xs text-white/60">End date (optional)</label>
                  <input data-testid="hol-end" type="date" value={endDate} min={date} onChange={(e) => setEndDate(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
                </div>
              </div>
              <div>
                <label className="text-xs text-white/60">Label</label>
                <input data-testid="hol-label" required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Public holiday, closure…" className="mt-1 w-full px-3 py-2.5 rounded-lg" />
              </div>
            </>
          )}

          <button
            data-testid="btn-add-holiday"
            disabled={scope === "leave-week" && (!empId || allLeaveDates.length === 0 || overBalance)}
            className="neon-btn w-full py-2.5 rounded-full text-sm flex items-center justify-center gap-2 disabled:opacity-40"
          >
            <CalendarPlus size={14} />
            {scope === "leave-week"
              ? allLeaveDates.length
                ? `Book ${allLeaveDates.length} day${allLeaveDates.length === 1 ? "" : "s"}`
                : "Book leave"
              : "Add"}
          </button>
        </form>

        <div className="lg:col-span-2 space-y-6">
          {["current", "upcoming", "past"].map((section) => {
            const list = hols.filter((h) => h._status === section);
            if (!list.length) return null;
            const label = section === "current" ? "Today" : section === "upcoming" ? "Upcoming" : "Past";
            return (
              <div key={section} className="glass rounded-2xl p-6">
                <h2 className="font-medium mb-4">{label} <span className="text-white/40 text-xs">({list.length})</span></h2>
                <ul className="space-y-2">
                  {list.map((h) => (
                    <li key={h.holiday_id} className="glass-solid rounded-xl p-4 flex items-center justify-between">
                      <div>
                        <div className="font-mono text-sm flex items-center gap-2">
                          {h.date}{h.end_date && h.end_date !== h.date ? ` → ${h.end_date}` : ""}
                          {/* Paid and unpaid absence look identical in a list
                              of dates, so the distinction is labelled. */}
                          {h.scope === "employee" && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                              PAID{h.hours_per_day ? ` ${h.hours_per_day}h` : ""}
                            </span>
                          )}
                          {h.scope === "unavailable" && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-white/50 border border-white/15">
                              N/A
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-white/60 mt-0.5">{h.label} · {h.scope === "shop" ? "Shop closed" : empName(h.employee_id)}</div>
                      </div>
                      <button onClick={() => del(h.holiday_id)} className="text-red-400 hover:bg-red-500/10 p-2 rounded-lg"><Trash2 size={14} /></button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          {hols.length === 0 && (
            <div className="glass rounded-2xl p-12 text-center text-white/40 text-sm">No holidays configured.</div>
          )}
        </div>
      </div>
    </div>
  );
}
