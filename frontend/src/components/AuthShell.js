import React, { useLayoutEffect } from "react";
import { Link } from "react-router-dom";

/**
 * The frame every signed-out page sits in: sign in, forgot password,
 * reset password. (Handoff: Sign in, doodle background.)
 *
 * One component rather than three copies. These pages have to look like
 * one place — a recovery link that opened onto a differently built page
 * reads as a phishing clone of the real one.
 *
 * The background is a tiling SVG pattern of roster motifs — clocks,
 * calendars, staff, shift bars, timesheets, rota grids, wages. Two layers
 * of the same tile: a small rotated one behind, the full-size one on top.
 * The motif set is defined once and referenced by both, so it can be
 * re-authored in one place, and it draws in currentColor so the colour
 * comes from the page's token rather than being baked into every stroke.
 * It is two <rect>s filled with patterns — no JS, no per-motif nodes, and
 * deliberately never animated.
 *
 * It also owns the theme. While a signed-out page is showing, the document
 * runs light to match this design — body, scrollbars and native controls
 * included — whatever the stored preference. The stored preference is not
 * touched, and the app re-applies it once signed in. useLayoutEffect so the
 * switch lands before the first paint.
 */

function DoodleField() {
  return (
    <svg className="si-bg si-doodles" aria-hidden="true" focusable="false">
      <defs>
        <g
          id="si-motifs"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
            <g transform="translate(18,26)"><circle cx="17" cy="17" r="16"></circle><path d="M17 8v9.6l6.4 4"></path></g>
            <g transform="translate(92,16)"><rect x="0" y="5" width="34" height="30" rx="4"></rect><path d="M8 0v9M26 0v9M0 15h34"></path></g>
            <g transform="translate(166,30)"><circle cx="11" cy="8" r="7"></circle><path d="M0 30c0-6.6 5-10.6 11-10.6S22 23.4 22 30"></path></g>
            <g transform="translate(228,34)"><rect x="0" y="0" width="52" height="20" rx="6"></rect><path d="M11 10h30"></path></g>
            <g transform="translate(300,22)"><path d="M0 16l8 8 16-18"></path><circle cx="14" cy="14" r="20" strokeDasharray="4 6"></circle></g>

            <g transform="translate(24,104)"><path d="M6 0h20v9c0 6-5 8-10 11-5-3-10-5-10-11V0z"></path><path d="M6 10h20v9c0 6-5 8-10 11-5-3-10-5-10-11v-9z"></path></g>
            <g transform="translate(96,112)"><path d="M0 26V8M11 26V0M22 26V14M33 26V5"></path><path d="M-3 32h40"></path></g>
            <g transform="translate(168,104)"><rect x="0" y="6" width="30" height="24" rx="4"></rect><path d="M30 13h8l6 7v10h-14z"></path><circle cx="9" cy="32" r="4"></circle><circle cx="34" cy="32" r="4"></circle></g>
            <g transform="translate(240,108)"><path d="M4 0h22M6 0l2 12c0 5 3 8 7 8s7-3 7-8l2-12"></path><path d="M15 20v10M8 30h14"></path></g>
            <g transform="translate(300,110)"><rect x="0" y="0" width="28" height="30" rx="3"></rect><path d="M6 8h16M6 15h16M6 22h10"></path></g>

            <g transform="translate(14,182)"><rect x="0" y="0" width="46" height="18" rx="5"></rect><path d="M56 2v14"></path></g>
            <g transform="translate(96,176)"><path d="M14 0C7 0 2 5 2 12c0 9 12 22 12 22s12-13 12-22c0-7-5-12-12-12z"></path><circle cx="14" cy="12" r="4.5"></circle></g>
            <g transform="translate(160,180)"><circle cx="16" cy="16" r="15"></circle><path d="M16 7v18M11.5 11h7a4 4 0 010 8h-5a4 4 0 000 8h7"></path></g>
            <g transform="translate(232,178)"><path d="M6 4h26l-4 12 4 12H6l4-12z"></path><path d="M6 0h26M6 32h26"></path></g>
            <g transform="translate(296,182)"><rect x="0" y="4" width="34" height="24" rx="4"></rect><path d="M0 12h34M9 20h6"></path></g>

            <g transform="translate(26,254)"><path d="M0 22c4-9 7-9 11 0s7 5 12-5"></path><path d="M0 30h26"></path></g>
            <g transform="translate(92,248)"><rect x="0" y="0" width="22" height="22" rx="3"></rect><rect x="30" y="0" width="22" height="22" rx="3"></rect><rect x="0" y="30" width="22" height="22" rx="3"></rect><rect x="30" y="30" width="22" height="22" rx="3"></rect></g>
            <g transform="translate(172,252)"><path d="M14 0C8 0 4 4 4 10v8l-4 6h28l-4-6v-8c0-6-4-10-10-10z"></path><path d="M10 28a4 4 0 008 0"></path></g>
            <g transform="translate(234,250)"><circle cx="15" cy="15" r="14"></circle><path d="M8 15l5 5 9-10"></path></g>
            <g transform="translate(298,252)"><path d="M0 4h30M4 4v22a4 4 0 004 4h14a4 4 0 004-4V4"></path><path d="M11 12v12M19 12v12"></path></g>

            <g transform="translate(60,64)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(200,74)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(286,88)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(70,150)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(212,146)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(140,222)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(276,230)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(46,320)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(150,330)"><circle cx="3" cy="3" r="3"></circle></g>
            <g transform="translate(250,318)"><circle cx="3" cy="3" r="3"></circle></g>

            <g transform="translate(120,300)"><path d="M0 8h40M34 2l6 6-6 6"></path></g>
            <g transform="translate(196,296)"><rect x="0" y="0" width="40" height="16" rx="5"></rect></g>
            <g transform="translate(300,300)"><circle cx="8" cy="8" r="14"></circle><path d="M8 0v8h8"></path></g>
            <g transform="translate(0,296)"><rect x="0" y="0" width="34" height="16" rx="5"></rect></g>
        </g>
        <pattern
          id="si-doodle-back"
          width="360"
          height="360"
          patternUnits="userSpaceOnUse"
          patternTransform="translate(180,120) rotate(8) scale(.62)"
        >
          <use href="#si-motifs" strokeOpacity=".07" />
        </pattern>
        <pattern id="si-doodle-front" width="360" height="360" patternUnits="userSpaceOnUse">
          <use href="#si-motifs" strokeOpacity=".12" />
        </pattern>
      </defs>
      {/* Behind first, then the full-size layer over it. */}
      <rect width="100%" height="100%" fill="url(#si-doodle-back)" />
      <rect width="100%" height="100%" fill="url(#si-doodle-front)" />
    </svg>
  );
}

export function WandMark() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5" />
    </svg>
  );
}

export default function AuthShell({ children, barRight = null, single = false }) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme");
    root.setAttribute("data-theme", "light");
    return () => {
      if (previous) root.setAttribute("data-theme", previous);
      else root.removeAttribute("data-theme");
    };
  }, []);

  return (
    <div className={single ? "si-page si-single" : "si-page"}>
      <div aria-hidden="true">
        <DoodleField />
        <div className="si-bg si-wash" />
        <div className="si-bg si-bloom si-bloom-a" />
        <div className="si-bg si-bloom si-bloom-b" />
        <div className="si-bg si-vignette" />
      </div>

      <div className="si-fore">
        <header className="si-bar">
          <Link to="/login" className="si-brand" aria-label="Roster — sign in">
            <span className="si-brand-mark"><WandMark /></span>
            <span>
              <span className="si-brand-name">Roster</span>
              <span className="si-brand-sub">Staff scheduling</span>
            </span>
          </Link>
          {barRight && <div className="si-bar-note">{barRight}</div>}
        </header>

        {children}
      </div>
    </div>
  );
}
