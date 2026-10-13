import React from "react";
import { GripVertical, Plus } from "lucide-react";

/**
 * The roles and seniority table: rank, role, how many staff hold it, the supervisory
 * switch, a drag handle and Remove, then a row to add a role.
 *
 * ONE COPY, USED TWICE. It is drawn on Shop settings and in the first-run setup wizard,
 * and was once written out separately in each. The two copies drifted apart: the settings
 * one was redesigned and the wizard kept the old list, so a new account's first sight of
 * its roles looked nothing like the screen it would use from then on. Sharing the markup
 * is what stops that happening again.
 *
 * It owns no state. The page keeps the list and the handlers (they are saved with the
 * rest of the shop settings) and passes them in, named as they are on the page.
 * Styles are the shared .ss-* ones in index.css; the wizard wraps this in .ss-embed,
 * which supplies the font and focus ring that .ss-page gives the settings screen.
 */
export default function RolesTable({
  roles, counts, cover,
  dragRole, setDragRole, overRole, setOverRole, dropRole,
  toggleCover, move, removeRole,
  newRole, setNewRole, addRole,
}) {
  return (
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
            data-testid={`role-row-${index}`}
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

      <p className="ss-note">
        <strong>Supervisory</strong> marks a role as counting for closing cover.
        If any roles are selected, at least one person in a selected role must
        cover every close. Selecting none turns off this shop setting's closing
        requirement. These selections are saved with your shop settings.
      </p>

      <div className="ss-addrow">
        <input
          data-testid="input-new-role"
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

    </div>
  );
}
