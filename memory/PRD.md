# Roster AI — PRD

## Original problem
Futuristic dark-glassmorphism SaaS to let retail managers configure shops, staff, holidays, and AI rules, then generate compliant weekly rosters in seconds with email dispatch and version workflow.

## User choices (locked)
- LLM: Claude Sonnet 4.5 via Emergent LLM Key
- Auth: JWT + Emergent-managed Google OAuth
- Email: Emergent-managed Resend
- Multi-store: single shop per account (v1)
- Payments: Emergent-managed Stripe claimable sandbox (Pro plan)

## Personas
- Retail owner / store manager
- Shift supervisor coordinating multi-role teams

## Implemented (Feb 2026)
- Auth: JWT signup/login + Google callback + pre-seeded owner `aneeshthimmapurmath@gmail.com / demo1234`
- Shop model + 4-step onboarding wizard (hours, min/max shift, roles)
- Employees CRUD with avatars, roles, age (under-16 flag), hourly rate, weekly max
- Holidays (shop + employee scope) + Fixed shift templates
- AI Rules engine (4 defaults + custom rules with toggles)
- Roster constraint solver (age curfew, hour caps, fixed shifts, holidays, manager coverage)
- Claude Sonnet 4.5 narrative summary per generated roster
- Weekly grid UI with inline shift editor, conflict badges, per-day coverage
- Compliance score, labor cost, utilization KPIs, activity log
- Approve (confetti) + Resend email dispatch to every employee (per-person cards)
- Roster versioning (v1.0 → v1.1) per week_start
- PDF / CSV export + Print view
- Stripe Pro plan checkout (monthly $19 / yearly $190) with success/cancel pages and `pro` flag on user

## Backlog (P1)
- Real-time timezone-aware scheduling per store
- Multi-store switching per account
- WhatsApp / SMS shift alerts (Twilio)
- Historical pattern learning refinement with per-employee preference weights
- Shift swap requests + employee self-service portal
