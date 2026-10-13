import React from "react";
import { Link } from "react-router-dom";

import AuthShell from "@/components/AuthShell";
import { DOCS, LegalDocument } from "@/components/LegalText";
import "@/styles/legal.css";

/**
 * The Terms of Service and Privacy Policy as full pages, at /terms and
 * /privacy.
 *
 * The sign-up form opens the same text in a small dialog, so people never leave
 * the form. These pages are still here because a policy needs a stable address
 * — to link from an email, to print, or to hand to a regulator or a customer.
 *
 * The text is not written here. It lives in components/LegalText.js and is
 * shared with the dialog, so the two cannot drift apart.
 */

function LegalPage({ kind }) {
  const doc = DOCS[kind];
  return (
    <AuthShell barRight={<Link to="/" className="si-link">Back to Roster</Link>}>
      <main className="legal-doc">
        <article>
          <h1 className="legal-h1">{doc.title}</h1>
          <LegalDocument kind={kind} />
        </article>
      </main>
    </AuthShell>
  );
}

export const PrivacyPage = () => <LegalPage kind="privacy" />;
export const TermsPage = () => <LegalPage kind="terms" />;
