import React, { useEffect, useRef, useState } from "react";
import { Content } from "@radix-ui/react-dialog";
import { Link } from "react-router-dom";
import { Dialog, DialogClose, DialogDescription, DialogOverlay, DialogPortal, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { addDays, buildRuns, fmtRange } from "@/pages/CalendarPage";
import "@/styles/roster-generate-review.css";

const leaveScopes = new Set(["employee", "unavailable", "sick"]);

function staffOnLeave(holidays, employees, week) {
  const names = new Map(employees.filter(person => person.is_active !== false)
    .map(person => [person.employee_id, person.name]));
  const end = addDays(week, 6);
  const entries = holidays
    .filter(leave => names.has(leave.employee_id) && leaveScopes.has(leave.scope)
      && leave.date <= end && (leave.end_date || leave.date) >= week)
    .map(leave => ({
      employee_id: leave.employee_id,
      date: leave.date < week ? week : leave.date,
      end_date: (leave.end_date || leave.date) > end ? end : leave.end_date,
      scope: "employee", // Merge consecutive days regardless of the type of leave.
    }));

  const people = new Map();
  for (const run of buildRuns(entries, id => names.get(id))) {
    if (!people.has(run.employeeId)) people.set(run.employeeId, { name: run.person, dates: [] });
    people.get(run.employeeId).dates.push(fmtRange(run.start, run.end));
  }
  return people;
}

export default function GenerateReviewDialog({ week, department, pinnedCount, trigger, onClose, onGenerate }) {
  const heading = useRef(null);
  const [result, setResult] = useState(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const request = { headers: { "X-Roster-Group": department }, signal: controller.signal, timeout: 8000 };
    Promise.all([
      api.get("/holidays", { ...request, params: { week_start: week } }),
      api.get("/employees", { ...request, params: { limit: 1000 } }),
    ]).then(([leave, employees]) => {
      if (!controller.signal.aborted) {
        setResult({ people: staffOnLeave(leave.data, employees.data, week) });
      }
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ error: true });
    });
    return () => controller.abort();
  }, [department, week, retry]);

  const people = result?.people;
  const count = people?.size;
  const date = new Date(`${week}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric",
  });

  return (
    <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
      <DialogPortal>
        <DialogOverlay className="roster-gen-overlay no-print" />
        <Content className="roster-gen-review no-print"
          onOpenAutoFocus={event => { event.preventDefault(); heading.current?.focus(); }}
          onCloseAutoFocus={event => { event.preventDefault(); if (trigger?.isConnected) trigger.focus(); }}>
          <header>
            <DialogTitle ref={heading} tabIndex={-1}>Review before generating</DialogTitle>
            <DialogDescription className="roster-gen-context">
              Week of <time dateTime={week}>{date}</time> · {department}
            </DialogDescription>
          </header>
          <div className="roster-gen-body">
            <div className="roster-gen-leave">
              <p className="roster-gen-summary" role="status">
                {!result ? "Checking leave for this week…"
                  : result.error ? "Could not check leave for this week."
                  : count === 0 ? "No leave recorded for this week."
                  : count === 1 ? "1 staff member has leave recorded this week"
                  : `${count} staff have leave recorded this week`}
              </p>
              <Link to={`/calendar?${new URLSearchParams({ week, group: department })}`}>Review leave</Link>
              {result?.error && <button type="button" onClick={() => {
                setResult(null);
                setRetry(current => current + 1);
              }}>Retry</button>}
              {count > 0 && <ul className="roster-gen-people" aria-label="Staff with recorded leave">
                {[...people].map(([id, person]) => <li key={id}>
                  <strong>{person.name}</strong>
                  <span>{person.dates.join(", ")}</span>
                </li>)}
              </ul>}
            </div>
            <ul className="roster-gen-prompts">
              <li>Has all leave for this week been entered?</li>
              <li>Has anyone’s availability, student break, or contract changed?</li>
              <li>Are there any changes to opening hours, fixed shifts, or coverage rules?</li>
            </ul>
            {pinnedCount > 0 && <p className="roster-gen-warning">
              Generating a new draft replaces the current draft and discards its pinned shifts.
            </p>}
          </div>
          <footer className="roster-gen-actions">
            <DialogClose className="wr-btn wr-btn-2">Go back</DialogClose>
            <button type="button" className="wr-btn wr-btn-1" disabled={!result} onClick={onGenerate}>
              Generate draft
            </button>
          </footer>
        </Content>
      </DialogPortal>
    </Dialog>
  );
}
