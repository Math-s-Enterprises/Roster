import React from "react";
import { Link } from "react-router-dom";

import AuthShell from "@/components/AuthShell";
import "@/styles/legal.css";

/**
 * Terms of Service and Privacy Policy, at /terms and /privacy.
 *
 * Written to cover the basics GDPR asks of a service like this: who is
 * responsible for the data (Art. 13), the controller/processor split and the
 * processing terms between them (Art. 28), the legal basis for each use
 * (Art. 6, and Art. 9 for sick-leave records), who receives the data and
 * where it goes (Arts. 13 and 44–49), how long it is kept, people's rights
 * (Arts. 15–22), automated decisions (Art. 22), breaches (Arts. 33–34) and
 * how to complain.
 *
 * Everything here describes what the app actually does. If the app changes —
 * a new provider, a new kind of data — change this text in the same change,
 * and raise the version so returning users can be asked to accept it again.
 *
 * This is a starting point, not legal advice. Have a solicitor or data
 * protection adviser review it before launch, especially the parts marked
 * for confirmation: retention, liability and governing law.
 */

// Fill these in once. While any is still a [placeholder], both pages show a
// draft notice, so they cannot go live half-finished by accident.
export const LEGAL = {
  version: "1.0",
  effectiveDate: "[DATE THESE TERMS TAKE EFFECT]",
  company: "[COMPANY LEGAL NAME]",
  companyNumber: "[COMPANY REGISTRATION NUMBER]",
  address: "[REGISTERED ADDRESS]",
  email: "[PRIVACY CONTACT EMAIL]",
  hosting: "[HOSTING PROVIDER AND REGION]",
  database: "[DATABASE PROVIDER AND REGION]",
  closureDays: "[NUMBER]",
  governingLaw: "Ireland",
};

const isPlaceholder = (value) => typeof value === "string" && value.startsWith("[");
export const IS_DRAFT = Object.values(LEGAL).some(isPlaceholder);

const Mail = () => <a className="legal-link" href={`mailto:${LEGAL.email}`}>{LEGAL.email}</a>;

function LegalPage({ title, lead, sections }) {
  return (
    <AuthShell barRight={<Link to="/" className="si-link">Back to Roster</Link>}>
      <main className="legal-doc">
        <article>
          <h1 className="legal-h1">{title}</h1>
          <p className="legal-meta">
            Version {LEGAL.version} · Effective {LEGAL.effectiveDate}
          </p>

          {IS_DRAFT && (
            <p className="legal-draft" role="note">
              <strong>Draft.</strong> Company details are still placeholders. Fill them in at the top
              of <code>src/pages/Legal.js</code> and have the text reviewed before going live.
            </p>
          )}

          <p className="legal-lead">{lead}</p>

          <nav className="legal-toc" aria-label="On this page">
            <ol>
              {sections.map((s) => (
                <li key={s.id}><a href={`#${s.id}`}>{s.heading}</a></li>
              ))}
            </ol>
          </nav>

          {sections.map((s) => (
            <section key={s.id} id={s.id} className="legal-section" aria-labelledby={`${s.id}-h`}>
              <h2 id={`${s.id}-h`} className="legal-h2">{s.heading}</h2>
              {s.body}
            </section>
          ))}
        </article>
      </main>
    </AuthShell>
  );
}

// --------------------------------------------------------------------------
// Privacy Policy
// --------------------------------------------------------------------------

const PRIVACY = [
  {
    id: "who",
    heading: "Who we are",
    body: (
      <p>
        Roster is a staff-scheduling service for businesses, provided by {LEGAL.company}
        {" "}({LEGAL.companyNumber}), {LEGAL.address}. For anything about your data, contact us
        at <Mail />.
      </p>
    ),
  },
  {
    id: "roles",
    heading: "Two kinds of information, two roles",
    body: (
      <>
        <p>
          <strong>Your account.</strong> When a manager signs up, we decide how that account
          information is used, so we are its <em>controller</em>.
        </p>
        <p>
          <strong>Your staff’s information.</strong> When a business enters its employees into
          Roster, the business decides what is collected and why. The business is the{" "}
          <em>controller</em>, and we are its <em>processor</em>: we handle that information only
          to provide the service, on the business’s instructions, under the data processing terms
          in our <Link className="legal-link" to="/terms">Terms of Service</Link>.
        </p>
        <p>
          If you work for a business that uses Roster and have a question about your information,
          please contact your employer first. We will help them answer it.
        </p>
      </>
    ),
  },
  {
    id: "what",
    heading: "What we collect",
    body: (
      <>
        <p><strong>Account information</strong></p>
        <ul>
          <li>Your name, email address and the name of your business.</li>
          <li>
            Your password, which we store only as a one-way hash, never the password itself — or,
            if you sign in with Google, your Google account email and identifier instead.
          </li>
        </ul>
        <p><strong>Staff information entered by the business</strong></p>
        <ul>
          <li>Names and email addresses, used to send each person their roster.</li>
          <li>
            Role, age, hourly rate, contracted and maximum hours, availability, preferred days off,
            employment type and student status, and which roster group they belong to.
          </li>
          <li>Holidays and other absences, and sick-leave records.</li>
          <li>The rosters, shifts and hours built from all of the above.</li>
          <li>Any past rosters you import, including spreadsheets, PDFs and photos.</li>
        </ul>
        <p>
          <strong>Sick-leave records are health data</strong>, which GDPR treats as a special
          category needing extra care. <strong>Age</strong> is collected because staff under 18
          have different working-time limits.
        </p>
        <p><strong>Other information</strong></p>
        <ul>
          <li>A record of actions taken in the app, such as approving a roster, kept for audit.</li>
          <li>
            Payment details are handled by Stripe. We never receive or store full card numbers.
          </li>
          <li>Standard technical logs kept by our hosting provider to run the service securely.</li>
        </ul>
      </>
    ),
  },
  {
    id: "why",
    heading: "Why we use it, and our legal basis",
    body: (
      <ul>
        <li>
          <strong>To provide the service and your account</strong> — necessary for our contract
          with you (GDPR Art. 6(1)(b)).
        </li>
        <li>
          <strong>To keep the service secure, prevent misuse and fix problems</strong> — our
          legitimate interest in running a safe service (Art. 6(1)(f)).
        </li>
        <li>
          <strong>Billing and tax records</strong> — our contract with you, and our legal
          obligations (Art. 6(1)(c)).
        </li>
        <li>
          <strong>Staff information</strong> — processed for the business, which relies on its own
          legal basis, usually the employment contract and its obligations as an employer. For
          sick-leave records, that is the condition for employment law in Art. 9(2)(b).
        </li>
      </ul>
    ),
  },
  {
    id: "automated",
    heading: "Automatically generated rosters",
    body: (
      <p>
        Roster proposes schedules automatically, but a manager reviews and approves every roster
        before it is used. No decision with legal or similarly significant effects on anyone is
        made by automated means alone.
      </p>
    ),
  },
  {
    id: "sharing",
    heading: "Who we share it with",
    body: (
      <>
        <p>
          We do not sell personal data or use it for advertising. We share it only with the
          service providers who help us run Roster, each bound to protect it:
        </p>
        <ul>
          <li><strong>Hosting and database</strong> — {LEGAL.hosting}; {LEGAL.database}.</li>
          <li><strong>Resend</strong> — sends email: password resets, and rosters to staff.</li>
          <li><strong>Stripe</strong> — takes payment for paid plans.</li>
          <li><strong>Google</strong> — only if you choose to sign in with Google.</li>
          <li>
            <strong>Google Fonts</strong> — the app’s typefaces are loaded from Google’s
            servers, which receive your device’s IP address when a page loads.
          </li>
          <li>
            <strong>Anthropic</strong> — only where AI features are switched on. Imported roster
            PDFs and photos are sent to be read, and short roster summaries, which can include
            staff names, are sent to be written.
          </li>
        </ul>
        <p>We disclose information to authorities only where the law requires it.</p>
      </>
    ),
  },
  {
    id: "transfers",
    heading: "International transfers",
    body: (
      <p>
        Some of these providers process data outside the European Economic Area, including in the
        United States. Where they do, the transfer relies on a recognised safeguard, such as the
        EU–US Data Privacy Framework or the European Commission’s Standard Contractual Clauses.
      </p>
    ),
  },
  {
    id: "retention",
    heading: "How long we keep it",
    body: (
      <ul>
        <li>
          Account, shop and staff information: for as long as the account is open. When an account
          is closed, we delete it within {LEGAL.closureDays} days, unless the law requires us to
          keep something longer.
        </li>
        <li>Billing records: for as long as tax law requires.</li>
        <li>Sign-in sessions expire after 7 days; password-reset links after an hour.</li>
        <li>
          Staff information is kept or deleted on the business’s instructions, and is deleted with
          the account.
        </li>
      </ul>
    ),
  },
  {
    id: "rights",
    heading: "Your rights",
    body: (
      <>
        <p>Under GDPR you have the right to:</p>
        <ul>
          <li>see the information we hold about you (access);</li>
          <li>have it corrected if it is wrong (rectification);</li>
          <li>have it deleted (erasure);</li>
          <li>limit how it is used (restriction);</li>
          <li>receive it in a portable format (portability);</li>
          <li>object to uses based on our legitimate interests (objection).</li>
        </ul>
        <p>
          To use any of these, email <Mail />. It is normally free, and we reply within one month,
          or tell you within that month if we need longer for a complex request. We may ask you to
          confirm your identity first. To close your account and have its data deleted, email us.
        </p>
      </>
    ),
  },
  {
    id: "complaints",
    heading: "Complaints",
    body: (
      <p>
        If you are unhappy with how we handle your information, please tell us first. You also have
        the right to complain to the Data Protection Commission in Ireland
        ({" "}<a className="legal-link" href="https://www.dataprotection.ie" target="_blank"
          rel="noopener noreferrer">dataprotection.ie</a>), or to the data protection authority
        where you live or work.
      </p>
    ),
  },
  {
    id: "security",
    heading: "How we protect it",
    body: (
      <>
        <p>
          Passwords are stored only as hashes. Every business’s data is kept separate from every
          other’s. Password-reset links work once and are stored only in a form that cannot be
          reversed. Access to the service needs a signed-in account.
        </p>
        <p>
          If a breach puts personal data at risk, we will report it to the Data Protection
          Commission within 72 hours where the law requires, and tell the people affected where
          the risk to them is high.
        </p>
      </>
    ),
  },
  {
    id: "storage",
    heading: "Cookies and browser storage",
    body: (
      <p>
        Roster keeps your sign-in and your light or dark theme preference in your browser’s
        storage. Both are needed for the service you asked for, so they do not need consent. We
        do not use analytics, advertising or tracking cookies. If you sign in with Google, Google
        may set its own cookies, under its own policy.
      </p>
    ),
  },
  {
    id: "children",
    heading: "Children",
    body: (
      <p>
        Roster is for businesses and is not intended for children. Staff under 18 may appear in a
        business’s rosters as employees; their information is handled by their employer as part
        of their employment.
      </p>
    ),
  },
  {
    id: "changes",
    heading: "Changes to this policy",
    body: (
      <p>
        We will post any changes here with a new version and date. For significant changes, we
        will also tell account holders by email.
      </p>
    ),
  },
];

export function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      lead="How Roster handles personal information: what we collect, why, who it goes to, how long we keep it, and the rights you have over it."
      sections={PRIVACY}
    />
  );
}

// --------------------------------------------------------------------------
// Terms of Service
// --------------------------------------------------------------------------

const TERMS = [
  {
    id: "about",
    heading: "About these terms",
    body: (
      <p>
        These terms are an agreement between {LEGAL.company} (“we”) and the business that
        creates a Roster account (“you”). By creating an account you confirm that you are at least
        18 and authorised to accept these terms on behalf of the business.
      </p>
    ),
  },
  {
    id: "service",
    heading: "The service",
    body: (
      <>
        <p>
          Roster helps you plan staff rosters. Rosters it generates are proposals: you review,
          change and approve them, and you remain responsible for the rosters you use.
        </p>
        <p>
          Roster checks rosters against working-time rules — rest periods, weekly hours, limits
          for young workers — to help you comply, but it does not guarantee compliance with
          employment law and is not legal advice.
        </p>
      </>
    ),
  },
  {
    id: "account",
    heading: "Your account",
    body: (
      <p>
        Keep your sign-in details secure; you are responsible for activity under your account.
        Tell us straight away at <Mail /> if you think someone else has used it.
      </p>
    ),
  },
  {
    id: "your-data",
    heading: "Your data and your staff’s data",
    body: (
      <>
        <p>You own the information you put into Roster. You are responsible for:</p>
        <ul>
          <li>having a lawful basis for the staff information you enter;</li>
          <li>
            telling your staff that their information is held in Roster and that rosters are
            emailed to them, for example in your staff privacy notice;
          </li>
          <li>keeping that information accurate, and entering only what you need.</li>
        </ul>
      </>
    ),
  },
  {
    id: "processing",
    heading: "Data processing terms",
    body: (
      <>
        <p>
          For staff information, you are the controller and we are your processor, as described in
          our <Link className="legal-link" to="/privacy">Privacy Policy</Link>. As your processor
          we will:
        </p>
        <ol>
          <li>process it only on your documented instructions — these terms and your use of the service — unless the law requires otherwise;</li>
          <li>make sure anyone who handles it is bound to confidentiality;</li>
          <li>protect it with appropriate technical and organisational security;</li>
          <li>use only the sub-processors listed in our Privacy Policy, on terms that protect it as these do, and tell you before adding or replacing one so you can object;</li>
          <li>help you respond to people exercising their rights;</li>
          <li>help you meet your obligations on security, breach notification and impact assessments;</li>
          <li>tell you without undue delay if we become aware of a personal data breach affecting it;</li>
          <li>when the service ends, delete it or return it to you, as you choose, unless the law requires us to keep it;</li>
          <li>give you the information needed to show we meet these obligations, and allow and contribute to audits.</li>
        </ol>
      </>
    ),
  },
  {
    id: "use",
    heading: "Acceptable use",
    body: (
      <p>
        Don’t use Roster for anything unlawful; try to reach another business’s data or another
        person’s account; disrupt or overload the service; or upload anything harmful, such as
        malware.
      </p>
    ),
  },
  {
    id: "plans",
    heading: "Plans and payment",
    body: (
      <p>
        Roster has a free plan and paid plans, billed monthly or yearly through Stripe. Prices are
        shown before you pay. A paid plan renews until you cancel; cancelling stops the next
        renewal.
      </p>
    ),
  },
  {
    id: "availability",
    heading: "Availability and changes",
    body: (
      <p>
        We work to keep Roster available and reliable, but cannot promise it will be uninterrupted
        or free of errors. We may improve or change features, and will give notice of changes that
        materially affect how you use it.
      </p>
    ),
  },
  {
    id: "liability",
    heading: "Liability",
    body: (
      <p>
        Nothing in these terms limits liability that cannot be limited by law.{" "}
        <strong>[To be completed with your legal adviser: the extent and cap of liability.]</strong>
      </p>
    ),
  },
  {
    id: "ending",
    heading: "Ending the agreement",
    body: (
      <p>
        You can close your account at any time by emailing <Mail />. We may suspend or close an
        account that seriously breaches these terms. When an account closes, its data is deleted
        as our Privacy Policy describes; ask us before closing if you want a copy first.
      </p>
    ),
  },
  {
    id: "law",
    heading: "Governing law",
    body: (
      <p>
        These terms are governed by the laws of {LEGAL.governingLaw}, and its courts have
        jurisdiction.
      </p>
    ),
  },
  {
    id: "changes",
    heading: "Changes to these terms",
    body: (
      <p>
        We will post changes here with a new version and date, and tell account holders by email
        before significant changes take effect. Where a change is significant, we will ask you to
        accept the new terms.
      </p>
    ),
  },
  {
    id: "contact",
    heading: "Contact",
    body: <p>{LEGAL.company}, {LEGAL.address}. Email: <Mail />.</p>,
  },
];

export function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      lead="The agreement between Roster and the businesses that use it, including the terms under which we process your staff’s information for you."
      sections={TERMS}
    />
  );
}
