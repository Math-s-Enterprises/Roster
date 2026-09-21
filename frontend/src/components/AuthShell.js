import React, { useLayoutEffect } from "react";
import { Link } from "react-router-dom";

/**
 * The frame every signed-out page sits in: sign in, forgot password,
 * reset password.
 *
 * One component rather than three copies, because the whole point is that
 * these pages look like one place — a recovery link that opened onto a
 * differently-built page would read as a phishing clone of the real one.
 *
 * It also owns the theme override. While any signed-out page is up the
 * document runs dark, whatever the stored preference, so leaving the app
 * from light mode and from dark mode lands on the same screen. The stored
 * preference is never touched, and the app re-applies it once signed in.
 * useLayoutEffect so the switch lands before the first paint.
 */

// One group of tiles, rendered twice so the scroll loops seamlessly.
const RIBBON = ["mint lg-tile-live", "empty", "violet", "pink", "empty", "mint", "amber"];

export default function AuthShell({ children, topLink, single = false }) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme");
    root.removeAttribute("data-theme");
    return () => {
      if (previous) root.setAttribute("data-theme", previous);
    };
  }, []);

  return (
    <div className="lg-page">
      <div aria-hidden="true">
        <div className="lg-bg lg-grid" />
        <div className="lg-bg lg-bloom lg-bloom-violet" />
        <div className="lg-bg lg-bloom lg-bloom-mint" />
        <div className="lg-bg lg-bloom lg-bloom-pink" />
        <div className="lg-bg lg-ribbon">
          <div className="lg-ribbon-track">
            {[...RIBBON, ...RIBBON].map((kind, i) => (
              <span key={i} className={`lg-tile lg-tile-${kind}`} />
            ))}
          </div>
        </div>
        <div className="lg-bg lg-scrim" />
        <div className="lg-bg lg-vignette" />
      </div>

      <div className="lg-fore">
        <div className="lg-bar">
          {topLink && (
            <Link to={topLink.to} className="lg-link">{topLink.label}</Link>
          )}
        </div>

        <main className={single ? "lg-content lg-content-single" : "lg-content"}>
          {children}
        </main>

        <footer className="lg-foot">
          <span>Roster · staff scheduling for shops</span>
          <span>Privacy · Terms</span>
        </footer>
      </div>
    </div>
  );
}

/** The gradient-bordered card, shared so every page's card is identical. */
export function AuthCard({ as: Tag = "div", children, ...rest }) {
  return (
    <div className="lg-card-outer">
      <Tag className="lg-card" {...rest}>{children}</Tag>
    </div>
  );
}
