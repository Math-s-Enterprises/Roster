import React, { useEffect, useState } from "react";
import { api, errorMessage, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { ChevronRight, ChevronLeft, Check, ArrowUp, ArrowDown, GripVertical, Loader2, Plus, X } from "lucide-react";

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [shop, setShop] = useState(null);
  const [name, setName] = useState("");
  const [hours, setHours] = useState([]);
  const [minShift, setMinShift] = useState(4);
  const [maxShift, setMaxShift] = useState(9);
  // The role list is ordered: position in it *is* the seniority ladder, which
  // decides who gets hours first and what order the roster grid is printed in.
  // Keeping one ordered list rather than a separate "roles" and "hierarchy"
  // means the two can never drift apart.
  const [roles, setRoles] = useState([]);
  const [newRole, setNewRole] = useState("");
  const [supervisory, setSupervisory] = useState([]);
  const [counts, setCounts] = useState({});
  const [strictDaysOff, setStrictDaysOff] = useState(true);
  const [breaksPaid, setBreaksPaid] = useState(false);
  const [open24h, setOpen24h] = useState(false);
  const [paidSickDays, setPaidSickDays] = useState(5);
  const [minRest, setMinRest] = useState(11);
  // People who are SENT the roster without appearing on it — an area
  // manager, a franchise owner. Not employees on purpose: an employee record
  // would put them in the seniority ladder, in the solver's candidate list
  // and on the printed rota, and sooner or later somebody would be rostered
  // a shift they do not work.
  const [observers, setObservers] = useState([]);
  const [observerName, setObserverName] = useState("");
  const [observerEmail, setObserverEmail] = useState("");
  const [saving, setSaving] = useState(false);
  // Explicit per-role supervisory flags. Seeded from the server's legacy
  // fallback for old shops, then saved as this shop's own choice.
  const [coverRoles, setCoverRoles] = useState(null);
  const [dragRole, setDragRole] = useState(null);
  const [overRole, setOverRole] = useState(null);
  const nav = useNavigate();

  /**
   * A shop already through setup sees every section at once with one Save,
   * not a five-screen wizard it has to click through to change one time.
   * Same fields either way, so the two can never disagree.
   */
  const editing = !!shop?.onboarded;

  const copyMondayToAll = () => {
    const monday = hours.find((h) => h.day === "mon") || hours[0];
    if (!monday) return;
    setHours(hours.map((h) => ({
      ...h, open: monday.open, close: monday.close, closed: monday.closed,
    })));
    toast.success(`Every day set to ${monday.open}–${monday.close}`);
  };

  useEffect(() => {
    Promise.all([api.get("/shop"), api.get("/shop/hierarchy")]).then(([r, h]) => {
      setShop(r.data); setName(r.data.name);
      setHours(r.data.hours); setMinShift(r.data.min_shift_hours);
      setMaxShift(r.data.max_shift_hours);
      setStrictDaysOff(r.data.strict_days_off !== false);
      setBreaksPaid(!!r.data.breaks_are_paid);
      setOpen24h(!!r.data.open_24h);
      setPaidSickDays(r.data.paid_sick_days ?? 5);
      setMinRest(r.data.min_rest_hours ?? 11);
      setObservers(r.data.roster_recipients || []);
      // Seeded from the server so an unconfigured shop starts from the
      // sensible default ladder rather than whatever order roles were added.
      setRoles(h.data.hierarchy);
      setSupervisory(h.data.supervisory);
      setCoverRoles(h.data.supervisory_roles || h.data.supervisory || []);
      setCounts(h.data.employee_counts || {});
    });
  }, []);

  const addObserver = () => {
    const email = observerEmail.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      toast.error("That does not look like an email address");
      return;
    }
    if (observers.some((o) => o.email.toLowerCase() === email.toLowerCase())) {
      toast.error("That address is already on the list");
      return;
    }
    setObservers([...observers, { name: observerName.trim(), email }]);
    setObserverName("");
    setObserverEmail("");
  };

  const move = (index, delta) => {
    const next = [...roles];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setRoles(next);
  };

  const dropRole = (target) => {
    if (!dragRole || dragRole === target) { setDragRole(null); setOverRole(null); return; }
    const next = [...roles];
    const from = next.indexOf(dragRole);
    const to = next.indexOf(target);
    if (from < 0 || to < 0) { setDragRole(null); setOverRole(null); return; }
    next.splice(to, 0, next.splice(from, 1)[0]);
    setRoles(next);
    setDragRole(null);
    setOverRole(null);
  };

  const save = async (extra = {}) => {
    await api.put("/shop", {
      name, hours,
      min_shift_hours: minShift, max_shift_hours: maxShift,
      roles,
      role_hierarchy: roles,
      strict_days_off: strictDaysOff,
      breaks_are_paid: breaksPaid,
      // The backend fills in round-the-clock hours and night templates when
      // this turns on, so the shop is never flagged 24h while still holding
      // 09:00–21:00 times.
      open_24h: open24h,
      paid_sick_days: Number(paidSickDays) || 0,
      min_rest_hours: Number(minRest) || 0,
      roster_recipients: observers,
      supervisory_roles: coverRoles || [],
      ...extra,
    });
  };

  const finish = async () => {
    await save({ onboarded: true });
    toast.success("Setup complete — you're ready to roster.");
    nav("/");
  };

  const saveChanges = async () => {
    setSaving(true);
    try {
      await save();
      toast.success("Shop settings saved");
    } catch (err) {
      toast.error(errorMessage(err, "Could not save the settings"));
    } finally { setSaving(false); }
  };

  if (!shop) return <div className="text-white/60">Loading…</div>;

  // ---- settings view ------------------------------------------------
  //
  // A shop already through setup gets the full settings page. First run
  // keeps the step-by-step wizard below: it is a different screen, and the
  // handoff this layout comes from covers settings only.

  /**
   * Which fields differ from what the server last sent. Drives the green
   * border on edited inputs, the list in the unsaved panel, and whether
   * Save is enabled — so all three can never disagree.
   */
  const dirty = {};
  if (shop) {
    if (name !== (shop.name || "")) dirty.name = "shop name";
    if (Number(minShift) !== Number(shop.min_shift_hours)) dirty.minShift = "min shift hours";
    if (Number(maxShift) !== Number(shop.max_shift_hours)) dirty.maxShift = "max shift hours";
    if (open24h !== !!shop.open_24h) dirty.open24h = "opening hours";
    if (strictDaysOff !== (shop.strict_days_off !== false)) dirty.strictDaysOff = "preferred days off";
    if (breaksPaid !== !!shop.breaks_are_paid) dirty.breaksPaid = "breaks are paid";
    if (Number(minRest) !== Number(shop.min_rest_hours ?? 11)) dirty.minRest = "minimum rest";
    if (Number(paidSickDays) !== Number(shop.paid_sick_days ?? 5)) dirty.paidSick = "paid sick days";
    if (JSON.stringify(roles) !== JSON.stringify(shop.role_hierarchy || shop.roles || [])) {
      dirty.roles = "roles and seniority";
    }
    if (JSON.stringify(observers) !== JSON.stringify(shop.roster_recipients || [])) {
      dirty.observers = "roster recipients";
    }
    if (coverRoles && JSON.stringify([...coverRoles].sort()) !== JSON.stringify([...supervisory].sort())) {
      dirty.cover = "supervisory cover";
    }
    if (JSON.stringify(hours) !== JSON.stringify(shop.hours || [])) dirty.hours = "opening hours";
  }
  const dirtyNames = [...new Set(Object.values(dirty))];
  const isDirty = dirtyNames.length > 0;

  // Validated here and re-validated server-side; 12 hours is the legal
  // ceiling, so a max above it is blocked rather than warned about.
  const invalid = {};
  if (Number(minShift) >= Number(maxShift)) {
    invalid.minShift = "Minimum must be less than the maximum.";
  }
  if (Number(maxShift) > 12) {
    invalid.maxShift = "12 hours is the legal ceiling — this cannot be saved.";
  }
  const blocked = Object.keys(invalid).length > 0;

  /** Whether a role counts as supervisory cover for this shop. */
  const cover = coverRoles || supervisory;

  const toggleCover = (role) => {
    const on = cover.includes(role);
    if (on && cover.length === 1) {
      toast.warning(
        "No role counts as supervisory cover — the \"manager on every close\" rule cannot be satisfied.",
      );
    }
    setCoverRoles(on ? cover.filter((r) => r !== role) : [...cover, role]);
  };

  const supervisoryCount = roles.filter((r) => cover.includes(r)).length;

  const addRole = () => {
    const title = newRole.trim();
    if (!title) return;
    if (roles.some((r) => r.toLowerCase() === title.toLowerCase())) {
      toast.error(`${title} is already on the list`);
      return;
    }
    setRoles([...roles, title]);
    setNewRole("");
    toast.success(`Added ${title} — set its cover in the table if it needs it`);
  };

  const removeRole = (role) => {
    if (!window.confirm(
      `Remove ${role} from the ladder?\n\n`
      + "Nobody loses the title — staff with a role that is not listed simply rank last."
    )) return;
    setRoles(roles.filter((r) => r !== role));
    setCoverRoles((current) => current?.filter((r) => r !== role) || []);
  };

  const removeObserver = (email) => {
    if (!window.confirm(`Stop sending the roster to ${email}?`)) return;
    setObservers(observers.filter((o) => o.email !== email));
  };

  const setDay = (day, patch) =>
    setHours(hours.map((h) => (h.day === day ? { ...h, ...patch } : h)));

  const FIXED_RULES = [
    "Nobody works more than 48 hours in a week, averaged over four months.",
    "Under-16s are never rostered before 08:00 or after 19:00.",
    "At least one supervisory person is rostered on every close.",
    "Booked holiday and sick leave are never scheduled over.",
  ];

  if (editing) {
    return (
      <div className="ss-page">
        <header className="ss-head">
          <div className="ss-eyebrow">SETUP</div>
          <h1 className="ss-h1">Shop settings</h1>
          <p className="ss-sub">
            Change anything you got wrong first time. Saving applies to the next roster you
            generate — weeks already approved are untouched.
          </p>
        </header>

        <div className="ss-split">
          <div className="ss-name-cell">
            <label className="ss-label" htmlFor="ss-name">Shop name</label>
            <input
              id="ss-name"
              data-testid="input-shop-name"
              className="ss-input"
              style={{ maxWidth: 520 }}
              value={name}
              data-dirty={Boolean(dirty.name)}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="ss-unsaved">
            <div className="ss-label">Unsaved changes</div>
            <p className="ss-unsaved-body" data-clean={!isDirty} role="status">
              {isDirty ? (
                <>
                  <strong>{dirtyNames.length} edit{dirtyNames.length === 1 ? "" : "s"}</strong>
                  {" — "}{dirtyNames.join(", ")}. Regenerate a week afterwards to see the effect.
                </>
              ) : "No unsaved changes."}
            </p>
          </div>
        </div>

        <div className="ss-section">
          <h2 className="ss-h2">Opening hours &amp; shift limits</h2>
          <p className="ss-section-sub">
            When the shop is open, and how long a single shift may run.
          </p>
        </div>
        <div className="ss-cells">
          <div className="ss-cell">
            <label className="ss-check">
              <input
                type="checkbox"
                data-testid="input-open-24h"
                checked={open24h}
                onChange={(e) => setOpen24h(e.target.checked)}
              />
              <span className="ss-box" aria-hidden="true">
                {open24h && <Check size={12} color="var(--t-on-accent)" strokeWidth={3} />}
              </span>
              <span className="ss-check-label">Open 24 hours</span>
            </label>
            <p className="ss-helper">
              The shop is treated as open every hour of every day, and at least one person is
              rostered at all times — including overnight. Individual day times are not used.
            </p>

            {/* Day times are kept, not cleared, so unticking restores them. */}
            {!open24h && (
              <>
                <div className="ss-days">
                  {DAYS.map((d) => {
                    const row = hours.find((h) => h.day === d) || { day: d, open: "09:00", close: "17:00" };
                    return (
                      <div className="ss-day" key={d}>
                        <span className="ss-day-name">{DAY_LABELS[d]}</span>
                        <span className="ss-day-times">
                          {row.closed ? (
                            <span className="ss-day-closed">Closed</span>
                          ) : (
                            <>
                              <input
                                type="time"
                                className="ss-time"
                                value={row.open || "09:00"}
                                aria-label={`${DAY_LABELS[d]} opening time`}
                                onChange={(e) => setDay(d, { open: e.target.value })}
                              />
                              <span style={{ color: "#6f6f6f" }}>→</span>
                              <input
                                type="time"
                                className="ss-time"
                                value={row.close || "17:00"}
                                aria-label={`${DAY_LABELS[d]} closing time`}
                                onChange={(e) => setDay(d, { close: e.target.value })}
                              />
                            </>
                          )}
                          <button
                            type="button"
                            className="ss-remove"
                            onClick={() => setDay(d, { closed: !row.closed })}
                          >
                            {row.closed ? "Open this day" : "Closed"}
                          </button>
                        </span>
                      </div>
                    );
                  })}
                </div>
                <button
                  type="button"
                  data-testid="btn-copy-monday"
                  className="ss-remove"
                  style={{ color: "#3ddc91", fontWeight: 700, marginTop: 10 }}
                  onClick={copyMondayToAll}
                >
                  Use Monday's times every day
                </button>
              </>
            )}
          </div>

          <div className="ss-cell">
            <label className="ss-label ss-label-tight" htmlFor="ss-min">Min shift hours</label>
            <input
              id="ss-min"
              type="number"
              className="ss-input ss-input-num"
              value={minShift}
              data-dirty={Boolean(dirty.minShift)}
              data-invalid={Boolean(invalid.minShift)}
              aria-describedby="ss-min-help"
              onChange={(e) => setMinShift(e.target.value)}
            />
            <p id="ss-min-help" className="ss-helper" data-invalid={Boolean(invalid.minShift)}>
              {invalid.minShift || "Shorter than this is not worth anybody's journey in."}
            </p>
          </div>

          <div className="ss-cell">
            <label className="ss-label ss-label-tight" htmlFor="ss-max">Max shift hours</label>
            <input
              id="ss-max"
              type="number"
              className="ss-input ss-input-num"
              value={maxShift}
              data-dirty={Boolean(dirty.maxShift)}
              data-invalid={Boolean(invalid.maxShift)}
              aria-describedby="ss-max-help"
              onChange={(e) => setMaxShift(e.target.value)}
            />
            <p
              id="ss-max-help"
              className="ss-helper"
              data-dirty={Boolean(dirty.maxShift) && !invalid.maxShift}
              data-invalid={Boolean(invalid.maxShift)}
            >
              {invalid.maxShift
                || (dirty.maxShift ? "Edited · the legal ceiling is 12 hours." : "The legal ceiling is 12 hours.")}
            </p>
          </div>
        </div>

        <div className="ss-section">
          <h2 className="ss-h2">Roles &amp; seniority <span>({roles.length})</span></h2>
          <p className="ss-section-sub">
            The order here is the ladder: hours are handed out from the top down, and the roster grid
            prints in the same order. Drag a role to move it.
          </p>
        </div>

        <div className="ss-table" role="table" aria-label="Roles and seniority">
          <div className="ss-row ss-colhead" role="row">
            <span role="columnheader">Rank</span>
            <span role="columnheader">Role</span>
            <span className="ss-num" role="columnheader">Staff</span>
            <span aria-hidden="true" />
            <span role="columnheader">Cover</span>
            <span role="columnheader" aria-label="Actions" />
          </div>

          {roles.map((role, index) => {
            const on = cover.includes(role);
            return (
              <div
                className="ss-row ss-rolerow"
                role="row"
                key={role}
                data-dragging={dragRole === role}
                data-dropbefore={overRole === role && dragRole !== role}
                draggable
                onDragStart={() => setDragRole(role)}
                onDragOver={(e) => { if (dragRole) { e.preventDefault(); setOverRole(role); } }}
                onDragLeave={() => setOverRole((r) => (r === role ? null : r))}
                onDrop={(e) => { e.preventDefault(); dropRole(role); }}
                onDragEnd={() => { setDragRole(null); setOverRole(null); }}
              >
                <span className="ss-rank" role="cell">{index + 1}</span>
                <span className="ss-role" role="cell">{role}</span>
                <span className="ss-num ss-staff" role="cell">{counts[role] ?? 0}</span>
                <span aria-hidden="true" />
                <span role="cell">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={on}
                    className="ss-cover"
                    data-on={on}
                    aria-label={`Supervisory cover for ${role}`}
                    onClick={() => toggleCover(role)}
                  >
                    <span className="ss-square" aria-hidden="true" />
                    Supervisory
                  </button>
                </span>
                <span className="ss-roleacts" role="cell">
                  <button
                    type="button"
                    className="ss-grip"
                    aria-label={`Reorder ${role}. Rank ${index + 1} of ${roles.length}. Use arrow keys.`}
                    onKeyDown={(e) => {
                      if (e.key === "ArrowUp") { e.preventDefault(); move(index, -1); }
                      if (e.key === "ArrowDown") { e.preventDefault(); move(index, 1); }
                    }}
                  >
                    <GripVertical size={15} strokeWidth={1.7} />
                  </button>
                  <button
                    type="button"
                    className="ss-remove"
                    onClick={() => removeRole(role)}
                    aria-label={`Remove ${role}`}
                  >
                    Remove
                  </button>
                </span>
              </div>
            );
          })}

          <div className="ss-addrow">
            <input
              className="ss-addinput"
              style={{ maxWidth: 420 }}
              value={newRole}
              placeholder="Add a role"
              aria-label="Add a role"
              onChange={(e) => setNewRole(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addRole(); }}
            />
            <button type="button" className="ss-btn" onClick={addRole} disabled={!newRole.trim()}>
              <Plus size={15} strokeWidth={2} /> Add
            </button>
          </div>

          <p className="ss-note">
            Tap <strong>Supervisory</strong> to set whether a role counts as supervisory cover — green
            is on, red is off. At least one supervisory person is rostered on every close. The
            scheduler also uses this shop's approved rosters to learn when supervisory cover is
            normally present.{" "}
            <strong>Removing a role does not remove it from anyone</strong> — staff with an unlisted
            title simply rank last.
            {supervisoryCount === 0 && (
              <span className="ss-warn">
                {" "}No role currently counts as supervisory cover, so the “manager on every close”
                rule cannot be satisfied.
              </span>
            )}
          </p>
        </div>

        <div className="ss-section">
          <h2 className="ss-h2">Scheduling rules</h2>
          <p className="ss-section-sub">How firmly the roster holds to preferences, and what it pays for.</p>
        </div>

        <div className="ss-cells ss-cells-wide ss-cells-divide">
          <div className="ss-cell">
            <label className="ss-check">
              <input
                type="checkbox"
                data-testid="input-strict-days-off"
                checked={strictDaysOff}
                onChange={(e) => setStrictDaysOff(e.target.checked)}
              />
              <span className="ss-box" aria-hidden="true">
                {strictDaysOff && <Check size={12} color="var(--t-on-accent)" strokeWidth={3} />}
              </span>
              <span className="ss-check-label">Preferred days off are never overridden</span>
            </label>
            <p className="ss-helper">
              A preferred day off is treated as unavailable rather than as a preference, so nobody is
              rostered on it even when the shop is short. Turn this off and the solver may use those
              days when it cannot cover the week any other way.
            </p>
          </div>

          <div className="ss-cell">
            <label className="ss-check">
              <input
                type="checkbox"
                data-testid="input-breaks-paid"
                checked={breaksPaid}
                onChange={(e) => setBreaksPaid(e.target.checked)}
              />
              <span className="ss-box" aria-hidden="true">
                {breaksPaid && <Check size={12} color="var(--t-on-accent)" strokeWidth={3} />}
              </span>
              <span className="ss-check-label">Breaks are paid</span>
            </label>
            <p className="ss-helper">
              With this off, an 8-hour shift pays 7.5 — the half hour of break is unpaid and comes out
              of the hours you are billed for. It does not change a full-time contract: the contracted
              week stays the same, and the difference shows in the Hours and Wages report.
            </p>
          </div>
        </div>

        <div className="ss-cells ss-cells-wide ss-cells-end">
          <div className="ss-cell">
            <label className="ss-label ss-label-tight" htmlFor="ss-rest">
              Minimum rest between shifts (hours)
            </label>
            <input
              id="ss-rest"
              type="number"
              className="ss-input ss-input-num"
              value={minRest}
              data-dirty={Boolean(dirty.minRest)}
              aria-describedby="ss-rest-help"
              onChange={(e) => setMinRest(e.target.value)}
            />
            <p id="ss-rest-help" className="ss-helper" data-dirty={Boolean(dirty.minRest)}>
              The Organisation of Working Time Act sets eleven consecutive hours between shifts.
              Lowering it below eleven does not make a shorter gap lawful — it only stops the roster
              flagging one, so raise it if your own agreements are stricter and leave it otherwise.
            </p>
          </div>

          <div className="ss-cell">
            <label className="ss-label ss-label-tight" htmlFor="ss-sick">Paid sick days per year</label>
            <input
              id="ss-sick"
              type="number"
              className="ss-input ss-input-num"
              value={paidSickDays}
              data-dirty={Boolean(dirty.paidSick)}
              aria-describedby="ss-sick-help"
              onChange={(e) => setPaidSickDays(e.target.value)}
            />
            <p id="ss-sick-help" className="ss-helper" data-dirty={Boolean(dirty.paidSick)}>
              {dirty.paidSick ? "Edited · " : ""}
              Irish statutory sick pay is the floor, not a target — you may pay more than the
              statutory minimum but not less. Days past the allowance are still recorded, as unpaid.
            </p>
          </div>
        </div>

        <div className="ss-section">
          <h2 className="ss-h2">Also send the roster to <span>({observers.length})</span></h2>
          <p className="ss-section-sub">
            People who receive the roster without appearing on it — an area manager, a franchise
            owner. They are never rostered and never counted as staff.
          </p>
        </div>

        <div className="ss-table">
          {observers.map((o) => (
            <div className="ss-reciprow" key={o.email}>
              <span className="ss-recip-name" data-none={!o.name}>{o.name || "No name"}</span>
              <span className="ss-recip-mail" title={o.email}>{o.email}</span>
              <span style={{ textAlign: "right" }}>
                <button
                  type="button"
                  className="ss-remove"
                  onClick={() => removeObserver(o.email)}
                  aria-label={`Remove ${o.email}`}
                >
                  Remove
                </button>
              </span>
            </div>
          ))}

          <div className="ss-addrow">
            <input
              className="ss-addinput"
              style={{ maxWidth: 240 }}
              value={observerName}
              placeholder="Name (optional)"
              aria-label="Recipient name (optional)"
              onChange={(e) => setObserverName(e.target.value)}
            />
            <input
              className="ss-addinput"
              style={{ maxWidth: 360 }}
              type="email"
              value={observerEmail}
              placeholder="name@example.com"
              aria-label="Recipient email"
              onChange={(e) => setObserverEmail(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addObserver(); }}
            />
            <button type="button" className="ss-btn" onClick={addObserver} disabled={!observerEmail.trim()}>
              <Plus size={15} strokeWidth={2} /> Add
            </button>
          </div>
        </div>

        <div className="ss-fixed">
          <div className="ss-label">Rules that cannot be turned off</div>
          <div className="ss-fixed-grid">
            {FIXED_RULES.map((line) => (
              <span className="ss-fixed-line" key={line}>{line}</span>
            ))}
          </div>
        </div>

        <div className="ss-save">
          <button
            type="button"
            data-testid="btn-save-settings"
            className="ss-save-btn"
            disabled={!isDirty || blocked || saving}
            onClick={saveChanges}
          >
            <Check size={15} strokeWidth={2.4} />
            {saving ? "Saving…" : "Save changes"}
          </button>
          <span className="ss-save-note">
            {blocked
              ? "Fix the highlighted fields before saving."
              : "Regenerate a week afterwards to see the effect."}
          </span>
        </div>
      </div>
    );
  }

  const steps = [
    { title: "Shop identity", desc: "Give your shop a name your team will recognize." },
    { title: "Opening hours", desc: "Set weekly opening and closing times." },
    { title: "Shift limits", desc: "Minimum and maximum shift lengths." },
    { title: "Roles & seniority", desc: "The order here decides who gets hours first." },
    { title: "Scheduling rules", desc: "How firmly the roster holds to preferences." },
  ];

  // In settings mode every section is rendered, so the `step === n` guards
  // below become "is this section shown", not "is this the current screen".
  const shows = (n) => editing || step === n;

  return (
    <div className="max-w-3xl">
      {editing ? (
        <div className="mb-8">
          <div className="eyebrow mb-2">Setup</div>
          <h1 className="display">Shop settings</h1>
          <p className="mt-2 text-sm" style={{ color: "var(--ink-mute)" }}>
            Change anything you got wrong first time. Saving applies to the
            next roster you generate — weeks already approved are untouched.
          </p>
        </div>
      ) : (
        <>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Onboarding · step {step + 1} of {steps.length}</div>
          <h1 className="text-4xl font-light mb-2">{steps[step].title}</h1>
          <p className="text-white/50 mb-8">{steps[step].desc}</p>
        </>
      )}

      <div className={editing ? "space-y-6" : "glass rounded-3xl p-8"}>
        {shows(0) && (
          <Section show={editing} title="Shop identity">
          <div className="space-y-4">
            <label className="text-xs text-white/60">Shop name</label>
            <input data-testid="input-shop-name" value={name} onChange={(e) => setName(e.target.value)} className="w-full px-4 py-3 rounded-xl" />
          </div>
          </Section>
        )}

        {shows(1) && (
          <Section show={editing} title="Opening hours">
          <div className="space-y-4">
            {/* Seven rows of near-identical times is the most tedious part of
                setup, and the commonest shapes are "same every day" and
                "always open". Both are one click. */}
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox" data-testid="input-open-24h"
                  checked={open24h}
                  onChange={(e) => setOpen24h(e.target.checked)}
                  className="w-4 h-4 accent-cyan-400"
                />
                Open 24 hours
              </label>

              {!open24h && (
                <button
                  type="button"
                  data-testid="btn-copy-monday"
                  onClick={copyMondayToAll}
                  className="px-3 py-1.5 rounded-lg glass-solid text-xs ml-auto"
                >
                  Use Monday's times every day
                </button>
              )}
            </div>

            {open24h ? (
              <p className="text-xs text-white/50">
                The shop is treated as open every hour of every day, and at
                least one person is rostered at all times — including
                overnight. Individual day times are not used.
              </p>
            ) : (
              <div className="space-y-3">
                {hours.map((h, i) => (
                  <div key={h.day} className="flex items-center gap-3">
                    <div className="w-14 text-sm">{DAY_LABELS[h.day]}</div>
                    <label className="flex items-center gap-2 text-xs text-white/60">
                      <input
                        type="checkbox"
                        checked={!h.closed}
                        onChange={(e) => {
                          const n = [...hours]; n[i] = { ...h, closed: !e.target.checked }; setHours(n);
                        }}
                      /> Open
                    </label>
                    <input type="time" value={h.open} disabled={h.closed}
                      onChange={(e) => { const n = [...hours]; n[i] = { ...h, open: e.target.value }; setHours(n); }}
                      className="px-3 py-2 rounded-lg font-mono" />
                    <span className="text-white/40 text-sm">to</span>
                    <input type="time" value={h.close} disabled={h.closed}
                      onChange={(e) => { const n = [...hours]; n[i] = { ...h, close: e.target.value }; setHours(n); }}
                      className="px-3 py-2 rounded-lg font-mono" />
                  </div>
                ))}
              </div>
            )}
          </div>
          </Section>
        )}

        {shows(2) && (
          <Section show={editing} title="Shift limits">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-white/60">Min shift hours</label>
              <input data-testid="input-min-shift" type="number" min={1} max={8} value={minShift} onChange={(e) => setMinShift(Number(e.target.value))} className="mt-1 w-full px-4 py-3 rounded-xl font-mono" />
            </div>
            <div>
              <label className="text-xs text-white/60">Max shift hours</label>
              <input data-testid="input-max-shift" type="number" min={4} max={12} value={maxShift} onChange={(e) => setMaxShift(Number(e.target.value))} className="mt-1 w-full px-4 py-3 rounded-xl font-mono" />
            </div>
          </div>
          </Section>
        )}

        {shows(3) && (
          <Section show={editing} title="Roles & seniority">
          <div className="space-y-4">
            <p className="text-xs text-white/50">
              Most senior at the top. Hours are allocated down this list, and
              the roster grid, print view and exports all follow the same
              order.
            </p>
            <ul className="space-y-2">
              {roles.map((r, i) => (
                <li key={r} data-testid={`role-row-${i}`} className="glass-solid rounded-xl px-3 py-2 flex items-center gap-3">
                  <span className="font-mono text-[11px] text-white/30 w-5 text-right">{i + 1}</span>
                  <span className="flex-1 text-sm truncate">{r}</span>
                  {counts[r] > 0 && (
                    <span className="text-[10px] text-white/40 font-mono shrink-0">
                      {counts[r]} staff
                    </span>
                  )}
                  {supervisory.includes(r) && (
                    <span className="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 shrink-0">
                      Supervisory
                    </span>
                  )}
                  <button type="button" title="Move up" disabled={i === 0}
                    onClick={() => move(i, -1)}
                    className="p-1 rounded text-white/40 hover:text-white disabled:opacity-20">
                    <ArrowUp size={13} />
                  </button>
                  <button type="button" title="Move down" disabled={i === roles.length - 1}
                    onClick={() => move(i, 1)}
                    className="p-1 rounded text-white/40 hover:text-white disabled:opacity-20">
                    <ArrowDown size={13} />
                  </button>
                  <button type="button" title="Remove"
                    onClick={() => {
                      setRoles(roles.filter((x) => x !== r));
                      setCoverRoles((current) => current?.filter((role) => role !== r) || []);
                    }}
                    className="p-1 rounded text-white/30 hover:text-red-400">
                    <X size={13} />
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input data-testid="input-new-role" value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                placeholder="Add a role" className="flex-1 px-4 py-2.5 rounded-xl" />
              <button type="button"
                onClick={() => {
                  const title = newRole.trim();
                  if (title && !roles.includes(title)) setRoles([...roles, title]);
                  setNewRole("");
                }}
                className="px-4 py-2.5 rounded-xl glass-solid text-sm">Add</button>
            </div>
            <p className="text-[11px] text-white/40">
              Roles in the top third count as supervisory cover. Removing a
              role here does not remove it from anyone — staff with an
              unlisted title simply rank last.
            </p>
          </div>
          </Section>
        )}

        {shows(4) && (
          <Section show={editing} title="Scheduling rules">
          <div className="space-y-5">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox" data-testid="input-strict-days-off"
                checked={strictDaysOff}
                onChange={(e) => setStrictDaysOff(e.target.checked)}
                className="mt-1 w-4 h-4 shrink-0 accent-cyan-400"
              />
              <span>
                <span className="text-sm block">Preferred days off are never overridden</span>
                <span className="text-xs text-white/50 block mt-1">
                  On: a requested day off is honoured even when that leaves an
                  hour uncovered — the gap is reported instead of quietly
                  filled. Off: preferences yield to keeping the shop attended.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox" data-testid="input-breaks-paid"
                checked={breaksPaid}
                onChange={(e) => setBreaksPaid(e.target.checked)}
                className="mt-1 w-4 h-4 shrink-0 accent-cyan-400"
              />
              <span>
                <span className="text-sm block">Breaks are paid</span>
                <span className="text-xs text-white/50 block mt-1">
                  On: a shift pays for its full length. Off: the break comes
                  out, so an 8-hour shift pays 7.5. This changes every wage
                  figure in the app. It does not change a full-time contract,
                  which is written in hours on the floor either way.
                </span>
              </span>
            </label>

            <div>
              <label className="text-xs text-white/60">Minimum rest between shifts (hours)</label>
              <input
                data-testid="input-min-rest-hours"
                type="number" min={0} max={24} step={0.5}
                value={minRest}
                onChange={(e) => setMinRest(e.target.value)}
                className="mt-1 w-32 px-4 py-2.5 rounded-xl font-mono"
              />
              <p className="text-xs text-white/50 mt-2 max-w-lg">
                Nobody starts again until this long after finishing. Eleven is
                the daily rest entitlement in the Organisation of Working Time
                Act. Counted in real time, so a night shift ending 07:00 on
                Tuesday blocks a Tuesday afternoon start.
              </p>
            </div>

            <div>
              <label className="text-xs text-white/60">Paid sick days per year</label>
              <input
                data-testid="input-paid-sick-days"
                type="number" min={0} max={365} step={0.5}
                value={paidSickDays}
                onChange={(e) => setPaidSickDays(e.target.value)}
                className="mt-1 w-32 px-4 py-2.5 rounded-xl font-mono"
              />
              <p className="text-xs text-white/50 mt-2 max-w-lg">
                Ireland's statutory minimum is 5. Set in days because that is
                how the law is written, but spent in hours: each person's day
                is worked out from the shifts they actually do, so somebody on
                four-hour Saturdays is not charged the same as somebody on
                ten-hour Mondays. Illness beyond the allowance is still
                recorded — it is simply unpaid.
              </p>
            </div>

            {/* Roster recipients. A shop setting rather than an employee,
                because these people do not work here — see the note on the
                state above. */}
            <div>
              <label className="text-xs text-white/60">
                Also send the roster to
              </label>
              <p className="text-xs text-white/50 mt-1 mb-3 max-w-lg">
                Anyone who should get the whole week's rota without being on
                it — an area manager, the owner. They receive every person and
                every shift, not their own. Name and email is all that is
                needed; they are not staff and are never rostered.
              </p>

              {observers.length > 0 && (
                <div className="space-y-2 mb-3 max-w-lg">
                  {observers.map((o, i) => (
                    <div key={`${o.email}-${i}`}
                         className="card-soft px-3 py-2 flex items-center gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] truncate">
                          {o.name || o.email}
                        </div>
                        {o.name && (
                          <div className="text-[11px] font-mono truncate"
                               style={{ color: "var(--ink-mute)" }}>{o.email}</div>
                        )}
                      </div>
                      <button
                        data-testid={`remove-observer-${i}`}
                        onClick={() => setObservers(
                          observers.filter((_, x) => x !== i))}
                        className="btn btn-ghost p-1.5 shrink-0"
                        title="Remove"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-2 flex-wrap max-w-lg">
                <input
                  data-testid="observer-name"
                  placeholder="Name (optional)"
                  value={observerName}
                  onChange={(e) => setObserverName(e.target.value)}
                  className="px-3 py-2 rounded-xl text-[13px]"
                  style={{ width: 150 }}
                />
                <input
                  data-testid="observer-email"
                  placeholder="their@email.com"
                  value={observerEmail}
                  onChange={(e) => setObserverEmail(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addObserver()}
                  className="px-3 py-2 rounded-xl text-[13px] flex-1"
                  style={{ minWidth: 180 }}
                />
                <button
                  data-testid="add-observer"
                  onClick={addObserver}
                  className="btn btn-secondary"
                >
                  <Plus size={13} /> Add
                </button>
              </div>
            </div>

            <div className="glass-solid rounded-xl p-4">
              <div className="text-xs text-white/60 mb-2">Rules that cannot be turned off</div>
              <ul className="text-xs text-white/50 space-y-1.5">
                <li>• Someone is on the floor from open to close, every day.</li>
                <li>• Hours are allocated down the seniority list above.</li>
                <li>• Nobody exceeds their contracted hours or the maximum shift length.</li>
                <li>• Under-16s are never rostered before 08:00 or after 19:00.</li>
              </ul>
            </div>
          </div>
          </Section>
        )}
      </div>

      {editing ? (
        <div className="flex items-center gap-3 mt-8">
          <button
            data-testid="btn-save-settings"
            onClick={saveChanges}
            disabled={saving}
            className="btn btn-primary"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Save changes
          </button>
          <span className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
            Regenerate a week afterwards to see the effect.
          </span>
        </div>
      ) : (
      <div className="flex justify-between mt-8">
        <button disabled={step === 0} onClick={() => setStep(step - 1)} className="px-5 py-2.5 rounded-full glass text-sm flex items-center gap-2 disabled:opacity-40">
          <ChevronLeft size={14} /> Back
        </button>
        {step < steps.length - 1 ? (
          <button data-testid="btn-next" onClick={async () => { await save(); setStep(step + 1); }} className="neon-btn px-6 py-2.5 rounded-full text-sm flex items-center gap-2">
            Continue <ChevronRight size={14} />
          </button>
        ) : (
          <button data-testid="btn-finish" onClick={finish} className="neon-btn px-6 py-2.5 rounded-full text-sm flex items-center gap-2">
            Finish <Check size={14} />
          </button>
        )}
      </div>
      )}
    </div>
  );
}

/**
 * One section of setup.
 *
 * A heading and a card only in settings mode: in the wizard the page title
 * already says which step you are on, and repeating it inside the card would
 * read as a stutter.
 */
function Section({ show, title, children }) {
  if (!show) return children;
  return (
    <div className="card p-6">
      <h2 className="text-sm font-medium mb-4">{title}</h2>
      {children}
    </div>
  );
}
