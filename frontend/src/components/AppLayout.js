import React, { useState } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Users, CalendarDays, Clock, ShieldCheck, Sparkles, LogOut, Menu, X, Wand2, Crown } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/employees", label: "Employees", icon: Users },
  { to: "/calendar", label: "Holidays", icon: CalendarDays },
  { to: "/fixed-shifts", label: "Fixed Shifts", icon: Clock },
  { to: "/rules", label: "AI Rules", icon: ShieldCheck },
  { to: "/roster", label: "Roster", icon: Wand2 },
  { to: "/pricing", label: "Billing", icon: Crown },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside
        className={`fixed lg:sticky top-0 left-0 h-screen w-64 z-40 glass p-6 flex flex-col transition-transform ${
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="flex items-center gap-2 mb-10">
          <div className="w-9 h-9 rounded-xl neon-gradient flex items-center justify-center">
            <Sparkles size={18} className="text-black" />
          </div>
          <div>
            <div className="text-sm font-semibold">Roster AI</div>
            <div className="text-[10px] text-white/40 tracking-wider uppercase">v1.0</div>
          </div>
        </div>

        <nav className="space-y-1 flex-1">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={`nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                  isActive
                    ? "bg-gradient-to-r from-cyan-500/10 to-violet-500/10 text-white border border-white/10"
                    : "text-white/60 hover:text-white hover:bg-white/5"
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-6 pt-6 border-t border-white/10">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-full neon-gradient flex items-center justify-center text-black font-semibold text-sm">
              {user?.name?.[0]?.toUpperCase() || "U"}
            </div>
            <div className="min-w-0">
              <div className="text-sm truncate flex items-center gap-1">{user?.name}{user?.pro && <Crown size={11} className="text-cyan-400" />}</div>
              <div className="text-[11px] text-white/40 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            data-testid="btn-logout"
            onClick={async () => { await logout(); navigate("/login"); }}
            className="w-full flex items-center gap-2 text-xs text-white/60 hover:text-white transition-colors"
          >
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      {/* Mobile toggle */}
      <button
        data-testid="btn-menu"
        className="lg:hidden fixed top-4 left-4 z-50 w-10 h-10 rounded-full glass flex items-center justify-center"
        onClick={() => setOpen(!open)}
      >
        {open ? <X size={16} /> : <Menu size={16} />}
      </button>

      {/* Main */}
      <main className="flex-1 min-w-0 p-6 lg:p-10">
        <Outlet />
      </main>
    </div>
  );
}
