import React, { createContext, useContext } from "react";
import { Link } from "react-router-dom";
import { LEGAL } from "@/components/legalDetails";

/**
 * The Terms of Service and the Privacy Policy - short, in plain language, one copy.
 *
 * Shown in two places that must never disagree: the small dialog that opens from
 * the sign-up form, and the pages at /terms and /privacy. Both render
 * <LegalDocument>, so editing a sentence here changes it everywhere.
 *
 * Everything here describes what the app actually does. If the app changes - a
 * new provider, a new kind of data, something new kept in the browser, a new
 * price - change this text in the same change, update LEGAL_UPDATED, and raise
 * LEGAL_VERSION if the change matters.
 *
 * TWO DETAILS. The text names who runs Roster and how to reach them, from legalDetails.js
 * (company, email). With no company set it says "the Roster team"; with no email set it
 * shows [YOUR EMAIL] in its place, deliberately visible, so the contact address can never
 * go live missing without anyone noticing.
 *
 * Typed into the wording, and so to be kept in step by hand: the plan prices
 * (Terms, Plans and payment), the 60-minute reset link and 7-day sign-in (Privacy,
 * How long we keep it), the 50 activity entries, and the list of providers.
 *
 * This is a starting point, not legal advice. Have a solicitor or data
 * protection adviser read it before launch.
 */

// The version belongs to the wording, so it lives with it, and is not shown. It is
// kept so that, when the app starts recording who accepted what, there is a version
// to record. The date IS shown: both documents promise that it changes when they do.
export const LEGAL_VERSION = "2.2";
export const LEGAL_UPDATED = "15 October 2026";

// The two details, trimmed. Empty means "not given yet": a visible blank is shown.
const COMPANY = String(LEGAL.company || "").trim();
const EMAIL = String(LEGAL.email || "").trim();

// "start" is for the place where the name begins a sentence, so the fallback gets its capital.
const Company = ({ start = false }) => <>{COMPANY || (start ? "The Roster team" : "the Roster team")}</>;
const Email = () => (
  EMAIL
    ? <a className="legal-link" href={`mailto:${EMAIL}`}>{EMAIL}</a>
    : <>[YOUR EMAIL]</>
);

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
        <Company start /> (“we”, “us”) runs Roster. For any question about your information, email{" "}
        <Email />.
      </>
    ),
  },
  {
    id: "roles",
    title: "Your details, and your staff’s.",
    body: (
      <ul>
        <li>For your own account details, we are responsible for how they are used.</li>
        <li>
          For details about staff that a business enters, the business is responsible and we handle
          them for it. If you are a staff member, please ask your employer first. You can also email
          us, tell us which business, and we will pass your request on.
        </li>
      </ul>
    ),
  },
  {
    id: "collect",
    title: "What we collect.",
    body: (
      <>
        <p><strong>About you</strong></p>
        <ul>
          <li>Your name and email address, and your password (stored scrambled; we have none if you only use Google).</li>
          <li>If you sign in with Google: your name, email and profile picture from Google. We never see your Google password.</li>
          <li>Your business name and settings: opening hours, roster groups, roles, shift and break rules.</li>
          <li>The names and emails of people you choose to send rosters to.</li>
          <li>Your plan and payment records, but not your card number. Stripe handles that.</li>
          <li>What you do in the app, such as “roster approved”, and when.</li>
          <li>Sign-in sessions and password-reset requests.</li>
        </ul>
        <p><strong>About your staff (entered by you)</strong></p>
        <ul>
          <li>Name, and email address if you add one.</li>
          <li>Job title, roster group, and whether they are still active.</li>
          <li>Age (13 or over). It is used for young-worker rules, such as the under-16 curfew check.</li>
          <li>Pay: an hourly rate, or a weekly or monthly salary for full-time contract staff.</li>
          <li>
            Whether they are on a full-time contract, a student or hourly, and their contract hours.
            For students, term-time hours and summer break dates.
          </li>
          <li>
            Availability: the days and times they can work, preferred days off, preferred shift, and
            whether they can work overnight.
          </li>
          <li>Holiday entitlement and balances, leave booked, and sick days.</li>
          <li>Sick-leave reports: the shift missed, who covered it, and an optional reason you type.</li>
          <li>Rosters, shifts, hours, breaks and labour cost; fixed shifts; and rules you write in plain words.</li>
          <li>
            Files you upload to import: roster photos, PDFs, spreadsheets and staff lists. We do not keep
            the file, only what was read from it.
          </li>
        </ul>
        <p>
          A sick-leave reason can reveal health information, which the law treats as especially
          sensitive. It is optional. Please keep it general (“unwell”).
        </p>
        <p><strong>On your device</strong></p>
        <ul>
          <li>
            We set no cookies of our own. Your browser keeps a few settings for Roster: your sign-in,
            colour theme, last roster group, display choices, your last 20 notifications (which can
            name staff) and a short count of wrong passwords typed for an email address (up to 15
            minutes). These stay on your device.
          </li>
          <li>
            When Roster loads, your browser asks Google for fonts, so Google can see your IP address.
            The sign-in screen also loads Google’s sign-in button.
          </li>
          <li>We use no analytics, no advertising and no session recording.</li>
        </ul>
      </>
    ),
  },
  {
    id: "why",
    title: "Why we use it.",
    body: (
      <>
        To run your account and rosters, take payment and keep billing records, keep Roster secure, and
        answer your questions. We do not sell personal information or use it for advertising. Roster
        suggests rosters; you review and approve them.
      </>
    ),
  },
  {
    id: "share",
    title: "Who we share it with.",
    body: (
      <>
        We share only what each one needs to do its job.
        <ul>
          <li>
            <strong>Anthropic (AI):</strong> reads roster images and PDFs you upload, turns plain-English
            rules into rules, and writes short roster summaries. It receives the uploaded images and PDFs
            (which show staff names and shifts), staff names and roles with the rule text, and roster
            totals and warnings.
          </li>
          <li><strong>Resend (email):</strong> sends password-reset emails and the rosters you choose to send.</li>
          <li>
            <strong>Stripe (payments):</strong> takes payment and manages plans. You give your card and
            billing details to Stripe directly.
          </li>
          <li><strong>Google:</strong> sign-in and fonts.</li>
          <li><strong>Our hosting providers:</strong> run Roster and store the data.</li>
          <li><strong>The people you email rosters to.</strong></li>
        </ul>
        <p>We also share information if the law requires it.</p>
      </>
    ),
  },
  {
    id: "abroad",
    title: "Outside Europe.",
    body: (
      <>
        Some of these providers may handle data outside the European Economic Area, including in the
        United States. Where they do, they rely on safeguards the law accepts, such as EU standard
        contractual clauses or an EU adequacy decision.
      </>
    ),
  },
  {
    id: "keep",
    title: "How long we keep it.",
    body: (
      <ul>
        <li>While your account is open, we keep what you put in.</li>
        <li>
          If you delete your account (account menu, Delete account), it is closed straight away and any
          plan is cancelled. We keep your data for 30 days in case you change your mind, then permanently
          delete everything. Signing in again within those 30 days cancels the deletion.
        </li>
        <li>
          If you press Reset all data on the Dashboard, your staff, rosters, rules and fixed shifts are
          deleted at once, and your account stays.
        </li>
        <li>The Dashboard shows your latest 50 activity entries. Older ones stay stored until the account is deleted.</li>
        <li>Password-reset links expire after 60 minutes. Your sign-in lasts up to 7 days.</li>
        <li>Stripe keeps its own payment records for as long as the law requires.</li>
      </ul>
    ),
  },
  {
    id: "rights",
    title: "Your rights.",
    body: (
      <>
        You can ask to see, correct or delete your information, to limit or object to how we use it,
        or to take a copy with you. In the app you can already edit what you entered and delete your
        account. For anything else, email <Email /> and we will reply within one month.
      </>
    ),
  },
  {
    id: "safe",
    title: "Keeping it safe.",
    body: (
      <>
        Passwords are stored scrambled. Each account’s data is kept apart, so you only see your own.
        Signing in is required, and card numbers never reach us.
        <p>
          If a breach puts your information at risk, we will tell the affected account holders and,
          where the law requires, the regulator, without undue delay. No system is perfectly secure, so
          use a strong password you use nowhere else.
        </p>
      </>
    ),
  },
  {
    id: "young",
    title: "Young people.",
    body: (
      <>
        Roster is for businesses: an account holder must be 18 or over. Employers can add staff aged 13
        and over, because age is needed for the young-worker rules. Employers are responsible for
        employing young people lawfully.
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes.",
    body: (
      <>
        If we change this policy, the new version replaces this one on this page, and the “Last updated”
        date changes. We do not email about changes, so please look from time to time. We will not use
        your information for a new purpose without first updating this page.
      </>
    ),
  },
  {
    id: "complaints",
    title: "Complaints.",
    body: (
      <>
        Please email us first at <Email />; we would like the chance to put it right. You can also
        complain to the Data Protection Commission, Ireland’s data protection regulator (
        <a
          className="legal-link"
          href="https://www.dataprotection.ie"
          target="_blank"
          rel="noopener noreferrer"
        >
          dataprotection.ie
        </a>
        ), or to the regulator in your own country.
      </>
    ),
  },
];

const TERMS = [
  {
    id: "about",
    title: "About Roster.",
    body: (
      <>
        Roster is run by <Company /> (“we”, “us”). It helps a business plan staff rosters, keep track of
        leave and sick days, estimate wage costs and email rosters to staff. These terms are between us
        and the business that opens an account (“you”). Roster is for businesses, not for personal use.
      </>
    ),
  },
  {
    id: "account",
    title: "Your account.",
    body: (
      <>
        You must be 18 or over and allowed to act for your business. Give true details and keep your
        password private. You are responsible for everything done through your account. If you think
        someone else has got in, email <Email /> straight away.
      </>
    ),
  },
  {
    id: "use",
    title: "Using Roster.",
    body: (
      <>
        Use Roster to run your own business’s staffing, and follow the law. Do not try to get into other
        accounts, overload the service, or copy it. Enter only what you need about your staff. Please
        keep sick-leave reasons general: “unwell” is enough.
      </>
    ),
  },
  {
    id: "staff",
    title: "Your staff’s information.",
    body: (
      <>
        What you put into Roster is yours. You decide what to enter about your staff, so you are
        responsible for having a good reason to hold it and for telling your staff what you hold.
        <p>
          We only use it to run Roster for you. We keep it confidential and secure, use only the
          providers named in the <LegalRef to="privacy">Privacy Policy</LegalRef>, help you answer your
          staff’s requests, tell you without delay if we learn of a breach, and erase it for good 30 days
          after you delete your account.
        </p>
      </>
    ),
  },
  {
    id: "aids",
    title: "Rosters, costs and AI are aids, not advice.",
    body: (
      <>
        Roster’s warnings, holiday and sick balances, wage costs and AI features can be wrong. Wage
        costs are estimates: for salaried staff they come from an hourly rate worked out from contract
        hours.
        <p>
          Check everything before you approve a roster, send it or pay anyone. You are responsible for
          following employment law and for paying your staff correctly. None of this is legal, tax or
          payroll advice.
        </p>
      </>
    ),
  },
  {
    id: "emails",
    title: "Emails Roster sends.",
    body: (
      <>
        When you send a roster, we email it to the addresses you entered. Only add addresses you are
        allowed to email. We also email you when you ask to reset your password. We use your staff’s
        addresses for nothing else.
      </>
    ),
  },
  {
    id: "plans",
    title: "Plans and payment.",
    body: (
      <>
        Some features may need a paid plan. Plans and prices are on the Pricing page when you buy. Today,
        Pro Monthly is €19 a month and Pro Yearly is €190 a year, plus tax where it applies. Stripe takes
        the payment; we never see your card number.
        <p>
          A paid plan renews automatically until you cancel. You can cancel at any time by deleting your
          account, which stops the plan straight away, or by emailing <Email />. We do not refund fees
          unless the law says we must. A new price applies from your next renewal.
        </p>
      </>
    ),
  },
  {
    id: "delete",
    title: "Deleting your account.",
    body: (
      <>
        You can delete your account at any time from the account menu (Delete account). We cancel your
        plan and close the account straight away, and you are signed out everywhere. We then keep your
        data for 30 days in case you change your mind. Nobody can see or use it in that time, and
        signing in again within the 30 days cancels the deletion and restores your account (your plan
        stays cancelled).
        <p>
          After 30 days everything is permanently deleted: your staff, rosters, leave and sick records,
          fixed shifts, AI rules, imports and history. This cannot be undone, so download what you need
          first. You can sign up again later with the same email once it has been deleted. Stripe keeps
          its own payment records, as the law requires.
        </p>
      </>
    ),
  },
  {
    id: "ending",
    title: "Ending.",
    body: (
      <>
        You can stop at any time by deleting your account. We can close an account if you seriously
        break these terms, use Roster unlawfully, or do not pay.
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes.",
    body: (
      <>
        We may update these terms. The new version replaces this one on this page, and the “Last
        updated” date at the top changes. We do not email about changes, so please look from time to
        time. If you carry on using Roster after a change, you accept it; if you do not, delete your
        account.
      </>
    ),
  },
  {
    id: "law",
    title: "Law and contact.",
    body: (
      <>
        These terms follow Irish law, and the Irish courts decide any dispute. Questions: <Email />.
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
      <p className="legal-updated">Last updated: {LEGAL_UPDATED}</p>

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
