import React, { createContext, useContext } from "react";
import { Link } from "react-router-dom";
import { LEGAL } from "@/components/legalDetails";

/**
 * The Terms of Service and the Privacy Policy - short, in plain language, one copy.
 *
 * Shown in two places that must never disagree: the small dialog that opens from
 * the sign-up form, and the pages at /terms and /privacy. Both render
 * <LegalDocument>, so editing a sentence here changes it everywhere. There is
 * deliberately no longer version behind this one: a customer who agrees to a
 * short summary while a different long text sits elsewhere would leave it unclear
 * which one governs.
 *
 * Short does not mean missing. Each point is one or two sentences, and between
 * them they still cover what GDPR asks of a notice and of a processor agreement:
 *
 *   Privacy Policy (Art. 13)  who is responsible and how to reach them; what is
 *     collected, and what is needed to sign up; the purpose and legal basis for
 *     each use; who receives it; transfers outside the EU and their safeguard;
 *     how long it is kept; the right to access, correct, delete, restrict,
 *     export and object; the right to complain; automated decisions; breaches.
 *   Terms (Art. 28)  the processor's duties: act only on instructions, keep it
 *     confidential and secure, use only named sub-processors, help with requests
 *     and breach duties, report breaches, delete or return the data, and allow
 *     checks.
 *
 * Everything here describes what the app actually does. If the app changes - a
 * new provider, a new kind of data, something new kept in the browser - change
 * this text in the same change, and raise LEGAL_VERSION below.
 *
 * GENERAL BY DEFAULT. The text reads properly with nothing filled in: it says
 * "Roster", "we" and "the business that creates a Roster account", and points to
 * "the contact details on our website". Three optional lines in legalDetails.js
 * (company, email, closureDays) make it more specific when they are filled in,
 * and the text adapts. Nothing is ever shown as an empty slot.
 *
 * Before real customers sign up, a privacy notice does need a way to contact
 * whoever is responsible (GDPR Art. 13(1)(a)), and a website needs to show its
 * operator's details somewhere (the e-Commerce rules). Filling in `company` and
 * `email` covers the first; the second can live in a site footer.
 *
 * This is a starting point, not legal advice. Have a solicitor or data
 * protection adviser review it before launch, especially liability, retention
 * and governing law.
 */

// The version and date belong to the wording, so they live with it. They are NOT
// shown to readers - the Terms and the Privacy Policy carry no version or date
// line. They are kept so that, when the app starts recording who accepted what,
// there is a version to record, and so a significant change can be told apart
// from a tidy-up. Raise the version when the wording changes in a way that
// matters, and update the date whenever the wording changes at all.
export const LEGAL_VERSION = "1.3";
export const LEGAL_UPDATED = "October 2026";

// The optional details, trimmed. Empty means "not given": the text stays general.
const COMPANY = String(LEGAL.company || "").trim();
const EMAIL = String(LEGAL.email || "").trim();
const DAYS = String(LEGAL.closureDays || "").trim();

const Mail = () => <a className="legal-link" href={`mailto:${EMAIL}`}>{EMAIL}</a>;

/** "Questions: email x@y" when we have an address; otherwise a pointer, not a gap. */
const Ask = () => (EMAIL ? <>email <Mail /></> : <>contact us using the details on our website</>);

/**
 * A reference from one document to the other.
 *
 * On a page it is an ordinary link. Inside the sign-up dialog it must not
 * navigate - that would throw away what has been typed into the form - so there
 * it swaps the dialog to the other document instead.
 */
const LegalNav = createContext({ open: null });
export const LegalNavProvider = LegalNav.Provider;

export function LegalRef({ to, children }) {
  const { open } = useContext(LegalNav);
  if (open) {
    return (
      <button type="button" className="legal-link legal-linkbtn" onClick={() => open(to)}>
        {children}
      </button>
    );
  }
  return <Link className="legal-link" to={`/${to}`}>{children}</Link>;
}

const PRIVACY = [
  {
    id: "who",
    title: "Who we are.",
    body: (
      <>
        “We” means Roster{COMPANY ? <>, run by {COMPANY}</> : null}. Questions: <Ask />. We post
        changes here and email you about significant ones.
      </>
    ),
  },
  {
    id: "account",
    title: "Your account.",
    body: (
      <>
        Your name, email, business name and a password (stored only as a hash) — or your Google
        email if you use Google. You need to give us these to create an account.
      </>
    ),
  },
  {
    id: "staff",
    title: "Your staff’s details.",
    body: (
      <>
        What you enter: names, emails, role, age, pay, hours, availability, holidays, sick leave
        (health data, so extra care) and imported rosters. Age matters because under-18s have
        different working-time limits.
      </>
    ),
  },
  {
    id: "roles",
    title: "Who decides.",
    body: (
      <>
        We decide how your account details are used. For your staff’s details, you decide and we act
        as your processor under the <LegalRef to="terms">Terms of Service</LegalRef>. Staff: ask
        your employer first.
      </>
    ),
  },
  {
    id: "why",
    title: "Why we use it.",
    body: (
      <>
        To run Roster (our contract with you), keep it secure (our legitimate interest) and keep
        billing records (a legal duty). We never sell it or use it for ads, and a manager approves
        every roster — nothing is decided automatically.
      </>
    ),
  },
  {
    id: "share",
    title: "Who gets it.",
    body: (
      <>
        Only providers that help us run Roster: our hosting and database providers, Resend (email),
        Stripe (payments), Google (fonts, and sign-in if you use it) and, if AI features are on,
        Anthropic (reads imported rosters, writes short summaries that can name staff). Some are
        outside the EU, including the US; we rely on the EU–US Data Privacy Framework or Standard
        Contractual Clauses.
      </>
    ),
  },
  {
    id: "keep",
    title: "How long we keep it.",
    body: (
      <>
        While your account is open, then we delete it {DAYS ? `within ${DAYS} days` : "promptly"} unless the law
        requires longer (such as billing records).
      </>
    ),
  },
  {
    id: "rights",
    title: "Your rights.",
    body: (
      <>
        See, correct, delete, restrict, export or object: <Ask /> (free; we reply within one
        month). You can also complain to the Data Protection Commission (
        <a
          className="legal-link"
          href="https://www.dataprotection.ie"
          target="_blank"
          rel="noopener noreferrer"
        >
          dataprotection.ie
        </a>
        ) or your local authority.
      </>
    ),
  },
  {
    id: "safe",
    title: "Keeping it safe.",
    body: (
      <>
        Each business’s data is kept separate. If a breach puts personal data at risk we report it
        within 72 hours where required, and tell those affected if the risk is high.
      </>
    ),
  },
  {
    id: "browser",
    title: "Cookies and browser storage.",
    body: (
      <>
        No cookies of our own and no analytics or tracking. Your browser keeps your sign-in, theme,
        roster group, layout choices, your last 20 notifications (kept for your account until you
        clear them) and, after wrong passwords, a short count of failed sign-in attempts. Google
        may set its own cookies if you use Google sign-in.
      </>
    ),
  },
];

const TERMS = [
  {
    id: "between",
    title: "Who this is between.",
    body: (
      <>
        {COMPANY || "Roster"} (“we”) and the business that creates a Roster account (“you”). You
        confirm you are 18 or over and can agree for your business.
      </>
    ),
  },
  {
    id: "does",
    title: "What Roster does.",
    body: (
      <>
        It suggests rosters and checks them against working-time rules. You approve every roster and
        stay responsible for it. It is not legal advice.
      </>
    ),
  },
  {
    id: "account",
    title: "Your account.",
    body: (
      <>
        Keep your sign-in secure and tell us if someone else uses it. You are responsible for what
        happens under it.
      </>
    ),
  },
  {
    id: "data",
    title: "Your data.",
    body: (
      <>
        You own it. You must have a lawful reason to hold your staff’s details, and tell them they
        are in Roster and are emailed their rosters.
      </>
    ),
  },
  {
    id: "role",
    title: "Our role with staff details.",
    body: (
      <>
        You are the controller; we are your processor. We use it only to run Roster for you, keep it
        confidential and secure, use only the providers in the{" "}
        <LegalRef to="privacy">Privacy Policy</LegalRef> (telling you before changes), help with
        staff requests and breaches, tell you without delay of any breach, allow checks by audit,
        and delete it or hand it back when you leave.
      </>
    ),
  },
  {
    id: "use",
    title: "Using Roster properly.",
    body: (
      <>
        No unlawful use, no reaching other businesses’ data or accounts, no overloading the service
        or harmful uploads.
      </>
    ),
  },
  {
    id: "plans",
    title: "Plans and payment.",
    body: (
      <>
        Free and paid plans, billed monthly or yearly through Stripe. Paid plans renew until you
        cancel.
      </>
    ),
  },
  {
    id: "changes",
    title: "Reliability and changes.",
    body: (
      <>
        We aim to keep Roster reliable but cannot promise it will never be interrupted. We email you
        before significant changes to these terms and ask you to accept them again.
      </>
    ),
  },
  {
    id: "ending",
    title: "Ending, liability and law.",
    body: (
      <>
        You can close your account any time by emailing us; we may close one that seriously breaks
        these terms. We do not limit liability the law does not allow us to limit. The laws of{" "}
        {LEGAL.governingLaw} apply.
      </>
    ),
  },
];

export const DOCS = {
  privacy: {
    title: "Privacy Policy",
    lead: "How Roster handles personal information.",
    points: PRIVACY,
  },
  terms: {
    title: "Terms of Service",
    lead: "The agreement between you and Roster.",
    points: TERMS,
  },
};

/** The document, without a frame around it: the dialog and the pages both use this. */
export function LegalDocument({ kind }) {
  const doc = DOCS[kind];
  return (
    <>
      <p className="legal-lead">{doc.lead}</p>

      <ul className="legal-points">
        {doc.points.map((point) => (
          <li key={point.id} id={`${kind}-${point.id}`}>
            <strong>{point.title}</strong> {point.body}
          </li>
        ))}
      </ul>
    </>
  );
}
