import React, { useCallback, useEffect, useState } from "react";
import { Outlet, NavLink, useLocation, useNavigate } from "react-router-dom";
import { Menu, Wand2, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { api, mondayOf } from "@/lib/api";
import ChangePasswordModal from "@/components/ChangePasswordModal";

/**
 * App shell (handoff: Sidebar).
 *
 * No icons in the nav, by design — the list is short enough to read, and
 * icons were adding noise the rest of the app does not use. Three hairline
 * bands, counts on the right where the number stays small and says
 * something, and the active item as an inset band with a green left bar.
 *
 * Counts are fetched once for the shell rather than per page, and refreshed
 * when the route changes — which is the only mutation signal available
 * without a shared cache. /rosters is asked for five records rather than its
 * default two hundred: the flag only needs the current week, and the full
 * list carries every shift of every roster.
 *
 * A zero renders as nothing rather than "0". An empty slot reads as nothing
 * to see; a zero reads as something broken.
 */

const GROUPS = [
  {
    label: "Setup",
    items: [
      { to: "/", label: "Dashboard", end: true },
      // Reachable after onboarding too: hours, roles and shift limits are the
      // settings most often got wrong first time, and there was no way back
      // to them once the wizard had been finished.
      { to: "/onboarding", label: "Shop Settings" },
      { to: "/employees", label: "Employees", countKey: "employees" },
      { to: "/calendar", label: "Holidays", countKey: "holidays" },
      { to: "/fixed-shifts", label: "Fixed Shifts", countKey: "fixedShifts" },
      { to: "/rules", label: "AI Rules", countKey: "aiRules" },
    ],
  },
  {
    label: "Scheduling",
    items: [
      { to: "/roster", label: "Roster", flagKey: "roster" },
      // No count: the archive grows without limit, so the number is noise.
      { to: "/past", label: "Past Rosters" },
    ],
  },
  {
    label: "Data",
    items: [
      { to: "/import", label: "Import Rosters" },
      { to: "/reports/hours", label: "Hours & Wages" },
      { to: "/reports/learning", label: "What It Learned" },
      { to: "/sick-report", label: "Sick Report", countKey: "sickOpen", tone: "warn" },
    ],
  },
];

const today = () => new Date().toISOString().slice(0, 10);

/** Whether an absence record covers today. */
const coversToday = (record) => {
  const day = today();
  const start = record.date;
  const end = record.end_date || record.date;
  return Boolean(start) && start <= day && day <= end;
};

export default function AppLayout() {
  const { user, logout } = useAuth();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const [counts, setCounts] = useState({});
  const [rosterFlag, setRosterFlag] = useState(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const loadCounts = useCallback(async () => {
    const [emps, holidays, fixed, rules, rosters] = await Promise.all([
      api.get("/employees").catch(() => null),
      api.get("/holidays").catch(() => null),
      api.get("/fixed-shifts").catch(() => null),
      api.get("/ai-rules").catch(() => null),
      api.get("/rosters", { params: { limit: 5 } }).catch(() => null),
    ]);

    const absences = holidays?.data || [];
    setCounts({
      employees: (emps?.data || []).filter((e) => e.is_active !== false && !e.past_staff).length,
      holidays: absences.filter((h) => h.scope === "employee" && coversToday(h)).length,
      fixedShifts: (fixed?.data || []).length,
      aiRules: (rules?.data || []).filter((r) => r.enabled !== false).length,
      sickOpen: absences.filter((h) => h.scope === "sick" && coversToday(h)).length,
    });

    if (rosters?.data) {
      const week = mondayOf();
      const current = rosters.data.find((r) => r.week_start === week);
      setRosterFlag(current ? (current.approved ? "approved" : "draft") : null);
    }
  }, []);

  useEffect(() => { loadCounts(); }, [loadCounts, pathname]);

  const signOut = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="nv-shell">
      {open && <div className="nv-backdrop" onClick={() => setOpen(false)} />}

      <button
        type="button"
        data-testid="btn-menu"
        className="nv-burger"
        aria-label={open ? "Close navigation" : "Open navigation"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <X size={17} /> : <Menu size={17} />}
      </button>

      <aside className="nv-side" data-open={open}>
        <div className="nv-brand">
          <span className="nv-mark" aria-hidden="true">
            <Wand2 size={17} color="#04140c" strokeWidth={1.7} />
          </span>
          <span style={{ minWidth: 0 }}>
            <span className="nv-brand-name" style={{ display: "block" }}>Roster</span>
            <span className="nv-brand-sub" style={{ display: "block" }}>Staff scheduling</span>
          </span>
        </div>

        <nav className="nv-nav" aria-label="Main">
          {GROUPS.map((group) => (
            <div className="nv-group" key={group.label}>
              <div className="nv-group-label">{group.label}</div>
              <ul className="nv-list">
                {group.items.map((item) => {
                  const count = item.countKey ? counts[item.countKey] : 0;
                  const flag = item.flagKey === "roster" ? rosterFlag : null;
                  return (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.end}
                        data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                        className="nv-item"
                        onClick={() => setOpen(false)}
                      >
                        <span>{item.label}</span>
                        {flag ? (
                          <span className="nv-flag" data-state={flag}>
                            {flag === "approved" ? "APPROVED" : "DRAFT"}
                          </span>
                        ) : count ? (
                          <span className="nv-count" data-tone={item.tone}>{count}</span>
                        ) : null}
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="nv-account">
          <div className="nv-acc-name" title={user?.name}>{user?.name}</div>
          <div className="nv-acc-mail" title={user?.email}>{user?.email}</div>
          <div className="nv-acc-acts">
            <button
              type="button"
              data-testid="btn-change-password"
              className="nv-acc-btn"
              onClick={() => setPasswordOpen(true)}
            >
              Change password
            </button>
            <button
              type="button"
              data-testid="btn-logout"
              className="nv-acc-btn"
              data-primary="true"
              onClick={signOut}
            >
              Sign out
            </button>
          </div>
          {passwordOpen && <ChangePasswordModal onClose={() => setPasswordOpen(false)} />}
        </div>
      </aside>

      <main className="nv-main">
        <Outlet />
      </main>
    </div>
  );
}
