import React, { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Wand2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import "@/styles/not-found.css";

export default function NotFound() {
  const { user, loading } = useAuth();
  const heading = useRef(null);
  const destination = user || loading ? "/" : "/login";

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Page not found | Roster";
    heading.current?.focus();
    return () => { document.title = previousTitle; };
  }, []);

  return (
    <div className="nf-page">
      <header className="nf-header">
        <Link to={destination} className="nf-brand" aria-label="Roster home">
          <span className="nf-mark"><Wand2 size={20} aria-hidden="true" /></span>
          <span><strong>Roster</strong><span className="nf-tagline">Staff scheduling</span></span>
        </Link>
      </header>
      <main className="nf-main" aria-labelledby="nf-heading">
        <div className="nf-code" aria-hidden="true">404</div>
        <p className="nf-eyebrow">A little off the roster</p>
        <h1 id="nf-heading" ref={heading} tabIndex={-1}>Page not found</h1>
        <p className="nf-description">This page may have moved, or the link may be incorrect. Let’s get you back on track.</p>
        <Link to={destination} className="nf-action">
          <ArrowLeft size={18} aria-hidden="true" />
          {loading ? "Back to home" : user ? "Back to dashboard" : "Go to sign in"}
        </Link>
      </main>
      <footer className="nf-footer">Right people. Right place. Right time.</footer>
    </div>
  );
}
