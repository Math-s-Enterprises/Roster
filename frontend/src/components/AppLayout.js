import React, { useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import {
  Archive, CalendarDays, Clock, Crown, LayoutDashboard, LogOut, Menu,
  Receipt, Settings, ShieldCheck, ThermometerSnowflake, Upload, Users, Wand2, X, TrendingDown, KeyRound,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import ChangePasswordModal from "@/components/ChangePasswordModal";

/**
 * App shell. See DESIGN.md — white canvas, hairline chrome, and no emerald
 * anywhere: the sidebar is navigation, and the one green button on screen
 * belongs to whatever the page's primary action is.
 */

// Grouped so a ten-item list reads as three short ones. The order follows the
// job: set the shop up, produce a roster, then look back at it.
const NAV_GROUPS = [
  {
    label: "Setup",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      // Reachable after onboarding too: hours, roles and shift limits are
      // the settings most often got wrong first time, and there was no way
      // back to them once the wizard had been finished.
      { to: "/onboarding", label: "Shop Settings", icon: Settings },
      { to: "/employees", label: "Employees", icon: Users },
      { to: "/calendar", label: "Holidays", icon: CalendarDays },
      { to: "/fixed-shifts", label: "Fixed Shifts", icon: Clock },
      { to: "/rules", label: "AI Rules", icon: ShieldCheck },
    ],
  },
  {
    label: "Scheduling",
    items: [
      { to: "/roster", label: "Roster", icon: Wand2 },
      { to: "/past", label: "Past Rosters", icon: Archive },
    ],
  },
  {
    label: "Data",
    items: [
      { to: "/import", label: "Import Rosters", icon: Upload },
      { to: "/reports/hours", label: "Hours & Wages", icon: Receipt },
      { to: "/reports/learning", label: "What It Learned", icon: TrendingDown },
      { to: "/sick-report", label: "Sick Report", icon: ThermometerSnowflake },
    ],
  },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--canvas)" }}>
      <aside
        className={`fixed lg:sticky top-0 left-0 h-screen w-60 z-40 flex flex-col border-r transition-transform ${
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
        style={{ background: "var(--canvas)", borderColor: "var(--hairline)" }}
      >
        <div className="px-5 py-5 border-b" style={{ borderColor: "var(--hairline-cool)" }}>
          <div className="flex items-center gap-2.5">
            <div
              className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
              style={{ background: "var(--primary)" }}
            >
              <Wand2 size={15} style={{ color: "var(--on-primary)" }} />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium leading-tight">Roster</div>
              <div className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
                Staff scheduling
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto scroll-thin px-3 py-4 space-y-5">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="eyebrow px-2 mb-1.5">{group.label}</div>
              <div className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    data-testid={`nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
                    onClick={() => setOpen(false)}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm transition-colors ${
                        isActive ? "font-medium" : ""
                      }`
                    }
                    style={({ isActive }) => ({
                      // The active row is a filled neutral surface rather than
                      // a coloured one — colour on screen means "action" or
                      // "problem", never "you are here".
                      background: isActive ? "var(--canvas-soft)" : "transparent",
                      color: isActive ? "var(--ink)" : "var(--ink-mute)",
                      boxShadow: isActive ? "inset 2px 0 0 var(--ink)" : "none",
                    })}
                  >
                    <Icon size={15} className="shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="px-3 py-4 border-t" style={{ borderColor: "var(--hairline-cool)" }}>
          <div className="flex items-center gap-2.5 px-2 mb-3">
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium shrink-0"
              style={{ background: "var(--canvas-soft)", border: "1px solid var(--hairline)", color: "var(--ink)" }}
            >
              {user?.name?.[0]?.toUpperCase() || "U"}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] truncate flex items-center gap-1">
                {user?.name}
                {user?.pro && <Crown size={11} style={{ color: "var(--ink-mute-2)" }} />}
              </div>
              <div className="text-[11px] truncate" style={{ color: "var(--ink-mute-2)" }}>
                {user?.email}
              </div>
            </div>
          </div>
          <button
            data-testid="btn-change-password"
            onClick={() => setPasswordOpen(true)}
            className="btn btn-ghost w-full justify-start text-[13px]"
          >
            <KeyRound size={14} /> Change password
          </button>
          <button
            data-testid="btn-logout"
            onClick={async () => { await logout(); navigate("/login"); }}
            className="btn btn-ghost w-full justify-start text-[13px]"
          >
            <LogOut size={14} /> Sign out
          </button>
          {passwordOpen && (
            <ChangePasswordModal onClose={() => setPasswordOpen(false)} />
          )}
        </div>
      </aside>

      {open && (
        <div
          className="lg:hidden fixed inset-0 z-30 bg-black/20"
          onClick={() => setOpen(false)}
        />
      )}

      <button
        data-testid="btn-menu"
        className="lg:hidden fixed top-4 left-4 z-50 w-9 h-9 rounded-md flex items-center justify-center"
        style={{ background: "var(--canvas-soft)", border: "1px solid var(--hairline-strong)", color: "var(--ink)" }}
        onClick={() => setOpen(!open)}
      >
        {open ? <X size={16} /> : <Menu size={16} />}
      </button>

      <main className="flex-1 min-w-0 p-6 lg:p-10">
        <Outlet />
      </main>
    </div>
  );
}
