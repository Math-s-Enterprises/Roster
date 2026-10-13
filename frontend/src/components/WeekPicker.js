import React, {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
} from "react";
import { createPortal } from "react-dom";
import { Calendar, ChevronDown, ChevronUp } from "lucide-react";
import "@/styles/week-picker.css";

/**
 * The calendar that opens from the Roster page's date field.
 *
 * WHY IT IS DRAWN BY THE APP AND NOT BY THE BROWSER
 *
 * The browser's own date popup could not be kept open on this page. Every click on
 * its month arrows changes the date, and this page reacts to a date change by
 * changing the address and reloading the roster; the popup closed each time, so
 * going back ten months meant opening it ten times. Past Rosters is fine only
 * because nothing there reacts. A popup the app draws itself cannot be closed by the
 * page behind it, and the month arrows here only change which month is SHOWN: the
 * page is not told anything until a day is chosen.
 *
 * The date field stays a real <input type="date"> so it can still be typed into and
 * stepped from the keyboard. Its browser popup is switched off (see the CSS) and
 * clicking the field, or the icon beside it, opens this one instead.
 *
 * WHAT IT DOES
 *   - Weeks run Monday to Sunday, as the roster does, and the chosen week is shown
 *     as a band, with its Monday marked.
 *   - The up arrow is the previous month and the down arrow the next, as in the
 *     browser's own popup, so nothing has to be relearned.
 *   - Choosing any day picks the week it falls in. "Today" picks this week.
 *
 * KEYBOARD (the WAI-ARIA date picker pattern)
 *   Arrows move a day or a week; Home and End go to the start and end of the week;
 *   Page Up and Page Down change month (with Shift, year); Enter or Space chooses;
 *   Escape closes and returns focus to where it was; Tab stays inside.
 *
 * All the date arithmetic is done in UTC, where every day is 24 hours long, so a
 * clock change can never move a day.
 */

const pad = (n) => String(n).padStart(2, "0");

/** "2026-09-05" -> a UTC Date, or null if it is not a real date. */
export function parseISO(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day); // not Date.UTC: years below 100 become 19xx there
  date.setUTCHours(0, 0, 0, 0);
  const real = date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
  return real ? date : null;
}

export const toISO = (date) =>
  `${String(date.getUTCFullYear()).padStart(4, "0")}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;

export function addDays(iso, days) {
  const date = parseISO(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return toISO(date);
}

/** Same day of the month, clamped: 31 Jan plus a month is 28 (or 29) Feb, never March. */
export function addMonths(iso, months) {
  const date = parseISO(iso);
  const day = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + months);
  const lastDay = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(day, lastDay));
  return toISO(date);
}

export function mondayOfISO(iso) {
  const date = parseISO(iso);
  const weekday = date.getUTCDay(); // 0 is Sunday
  date.setUTCDate(date.getUTCDate() + (weekday === 0 ? -6 : 1 - weekday));
  return toISO(date);
}

/** The month containing `iso` as six rows of seven days, starting on a Monday. */
export function monthGrid(iso) {
  const date = parseISO(iso);
  const first = toISO(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)));
  const start = mondayOfISO(first);
  return Array.from({ length: 6 }, (_, row) =>
    Array.from({ length: 7 }, (_, col) => addDays(start, row * 7 + col)));
}

/** Today by the clock on the wall, which is what "today" means to the person looking. */
export function todayISO() {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const say = (iso, options) => parseISO(iso).toLocaleDateString(undefined, { ...options, timeZone: "UTC" });
const monthTitle = (iso) => say(iso, { month: "long", year: "numeric" });
const fullDate = (iso) => say(iso, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const WEEKDAYS = Array.from({ length: 7 }, (_, i) => addDays("2024-01-01", i)); // 1 Jan 2024 was a Monday

const FOCUSABLE = 'button:not([disabled]):not([tabindex="-1"])';

export default function WeekPicker({ value, onPick, children }) {
  const [open, setOpen] = useState(false);
  const [focusDate, setFocusDate] = useState(null); // the day with the keyboard focus, and so the month on show
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const boxRef = useRef(null);
  const popRef = useRef(null);
  const openerRef = useRef(null);
  const moveFocus = useRef(false);
  const titleId = useId();

  const chosenMonday = useMemo(() => mondayOfISO(parseISO(value) ? value : todayISO()), [value]);
  const today = todayISO();

  const show = useCallback(() => {
    openerRef.current = document.activeElement;
    setFocusDate(chosenMonday);
    moveFocus.current = true; // on opening, focus lands on the chosen day
    setOpen(true);
  }, [chosenMonday]);

  const hide = useCallback((restoreFocus = true) => {
    setOpen(false);
    const opener = openerRef.current;
    openerRef.current = null;
    if (restoreFocus && opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
  }, []);

  const pick = (iso) => {
    onPick(iso);
    hide();
  };

  // Sit under the control, against its right edge, and stay on screen.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const place = () => {
      const anchor = boxRef.current?.closest(".wr-weeknav") || boxRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const width = 296;
      let right = window.innerWidth - rect.right;
      if (window.innerWidth - right - width < 8) right = Math.max(8, window.innerWidth - width - 8);
      setPos({ top: Math.round(rect.bottom + 6), right: Math.round(right) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  // A click anywhere else closes it. (Its own clicks, and the field's, do not.)
  useEffect(() => {
    if (!open) return undefined;
    const away = (event) => {
      if (popRef.current?.contains(event.target) || boxRef.current?.contains(event.target)) return;
      hide(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open, hide]);

  // Keyboard focus follows the day, but only when the keyboard moved it. A click on
  // a month arrow must leave focus on the arrow, so it can be pressed again.
  useEffect(() => {
    if (!open || !moveFocus.current || !popRef.current) return;
    moveFocus.current = false;
    popRef.current.querySelector(`[data-date="${focusDate}"]`)?.focus();
  }, [open, focusDate]);

  const goToMonth = (months) => {
    // If focus is on a day, that day may not be in the next month's grid. Carry the
    // focus to the day that is, or it falls back to the page behind the calendar.
    if (popRef.current?.querySelector(".wp-grid")?.contains(document.activeElement)) moveFocus.current = true;
    setFocusDate((current) => addMonths(current, months));
  };

  const onGridKeyDown = (event) => {
    let next = null;
    const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (steps[event.key]) next = addDays(focusDate, steps[event.key]);
    else if (event.key === "Home") next = mondayOfISO(focusDate);
    else if (event.key === "End") next = addDays(mondayOfISO(focusDate), 6);
    else if (event.key === "PageUp") next = addMonths(focusDate, event.shiftKey ? -12 : -1);
    else if (event.key === "PageDown") next = addMonths(focusDate, event.shiftKey ? 12 : 1);
    if (!next) return;
    event.preventDefault();
    moveFocus.current = true;
    setFocusDate(next);
  };

  // Escape and Tab are heard for the whole page while the calendar is open, not only
  // inside it. Focus can end up on the page behind (a browser that does not focus a
  // button when it is clicked, or a day that has scrolled out of the month), and
  // Escape must still close it and Tab must still lead back in.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        hide();
        return;
      }
      if (event.key !== "Tab" || !popRef.current) return;
      const stops = [...popRef.current.querySelectorAll(FOCUSABLE)];
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!popRef.current.contains(active)) {
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
    return () => document.removeEventListener("keydown", onKey);
  }, [open, hide]);

  const rows = open ? monthGrid(focusDate) : [];
  const shownMonth = open ? parseISO(focusDate).getUTCMonth() : 0;

  return (
    <div
      className="wr-picker wp-box"
      ref={boxRef}
      onClick={(event) => {
        // Clicking the date itself opens the calendar, as it always did.
        if (open || event.target.closest(".wp-trigger")) return;
        show();
      }}
    >
      <button
        type="button"
        className="wp-trigger"
        data-testid="week-calendar-button"
        aria-label="Open calendar"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          if (open) hide(); else show();
        }}
      >
        <Calendar size={14} strokeWidth={1.6} aria-hidden="true" />
      </button>

      {children}

      {open && createPortal(
        <div
          ref={popRef}
          className="wp-pop"
          data-testid="week-calendar"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          style={{ top: pos.top, right: pos.right }}
          // React sends a portal's clicks up through the tree to the box, which
          // would reopen it; they are the calendar's own.
          onClick={(event) => event.stopPropagation()}
        >
          <div className="wp-head">
            <h2 id={titleId} className="wp-month" data-testid="week-calendar-month" aria-live="polite">
              {monthTitle(focusDate)}
            </h2>
            <div className="wp-nav">
              <button
                type="button"
                className="wp-navbtn"
                data-testid="week-calendar-prev"
                aria-label="Previous month"
                title="Previous month"
                onClick={() => goToMonth(-1)}
              >
                <ChevronUp size={16} strokeWidth={2} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="wp-navbtn"
                data-testid="week-calendar-next"
                aria-label="Next month"
                title="Next month"
                onClick={() => goToMonth(1)}
              >
                <ChevronDown size={16} strokeWidth={2} aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="wp-grid" role="grid" aria-labelledby={titleId} onKeyDown={onGridKeyDown}>
            <div className="wp-row" role="row">
              {WEEKDAYS.map((iso) => (
                <div className="wp-dow" role="columnheader" key={iso}>
                  {say(iso, { weekday: "short" })}
                </div>
              ))}
            </div>
            {rows.map((week) => (
              <div className="wp-row" role="row" key={week[0]}>
                {week.map((iso) => {
                  const inChosenWeek = mondayOfISO(iso) === chosenMonday;
                  return (
                    <div
                      className="wp-cell"
                      role="gridcell"
                      key={iso}
                      aria-selected={inChosenWeek}
                      data-week={inChosenWeek}
                    >
                      <button
                        type="button"
                        className="wp-day"
                        data-date={iso}
                        data-outside={parseISO(iso).getUTCMonth() !== shownMonth}
                        data-selected={iso === chosenMonday}
                        data-today={iso === today}
                        tabIndex={iso === focusDate ? 0 : -1}
                        aria-label={fullDate(iso)}
                        aria-current={iso === today ? "date" : undefined}
                        onClick={() => pick(iso)}
                      >
                        {parseISO(iso).getUTCDate()}
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          <div className="wp-foot">
            <button type="button" className="wp-link" data-testid="week-calendar-today" onClick={() => pick(todayISO())}>
              Today
            </button>
            <button type="button" className="wp-link wp-link-mute" data-testid="week-calendar-close" onClick={() => hide()}>
              Close
            </button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
