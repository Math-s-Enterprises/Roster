#!/usr/bin/env node
/**
 * One continuous absence per person is one row.
 *
 *     node check-leave-runs.js
 *
 * WHY THIS EXISTS
 * ---------------
 * `buildRuns` in pages/CalendarPage.js is the whole point of the Holidays
 * redesign. The old page rendered four consecutive single-day records for
 * one person as four identical rows, so nobody could tell how long anybody
 * was actually off.
 *
 * Two rules, and both have already been got wrong once:
 *
 *   1. ADJACENT DAYS for one person join into a run. A gap breaks it, and a
 *      different person never joins it — merging people onto a shared row
 *      was the first design and the 3a revision reversed it, because a row
 *      for four people has one Edit button and no answer to "whose booking
 *      is this".
 *
 *   2. PAY TYPE DOES NOT BREAK A RUN. Thirteen days off with four of them
 *      paid is ONE absence tagged "Holiday · 9 unpaid + 4 paid" — not three
 *      bookings with gaps between them, which is what the first version
 *      produced and what 3a exists to fix. Sick is NOT folded in the same
 *      way: it is a different kind of absence, not a different way of
 *      paying for one.
 *
 * Rule 2 is the exact inverse of what this file asserted a revision ago, so
 * the cases below are written to fail loudly if anyone reinstates the old
 * behaviour by reflex.
 *
 * There is no jest setup in this app, and a production build needs more
 * memory than a sandbox usually has. This runs in plain node in about a
 * second, in the same spirit as check-css-vars.js: the cheapest thing that
 * would actually have caught the bug.
 *
 * Sabotage-checked — see the commit message for which change fails which
 * case.
 */
const babel = require('@babel/core');
const fs = require('path') && require('fs');
const vm = require('vm');
const path = require('path');

/* The page imports React, the API client and icons, none of which the pure
   helpers touch. Stubbed rather than mocked: nothing at the top level of the
   module has a side effect, so the real code runs unmodified. */
const STUBS = `
const React={Fragment:'F',createElement:()=>null};
const useEffect=()=>{},useMemo=(f)=>f(),useState=(v)=>[v,()=>{}];
const api={},errorMessage=()=>'',toast={};
const CalendarPlus=null,Download=null,Plus=null,X=null;
const DAYS=['mon','tue','wed','thu','fri','sat','sun'];
const DAY_SHORT={mon:'Mon',tue:'Tue',wed:'Wed',thu:'Thu',fri:'Fri',sat:'Sat',sun:'Sun'};
function mondayOf(s){const d=new Date(s+'T00:00:00');const w=d.getDay();
  d.setDate(d.getDate()+(w===0?-6:1-w));
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
`;

function loadPage() {
  const file = path.join(__dirname, 'src', 'pages', 'CalendarPage.js');
  const source = fs.readFileSync(file, 'utf8').replace(/^import .*?;$/gms, '');
  const code = babel.transformSync(STUBS + source, {
    presets: [
      [require.resolve('@babel/preset-env'), { targets: { node: 'current' } }],
      require.resolve('@babel/preset-react'),
    ],
    configFile: false,
    babelrc: false,
  }).code;
  const module_ = { exports: {} };
  new vm.Script(code).runInNewContext({
    module: module_, exports: module_.exports, require, console,
    Intl, Date, Math, Map, Set, JSON, Object, Array, String, Number, Boolean,
  });
  return module_.exports;
}

const { buildRuns, tagFor } = loadPage();

const NAMES = {
  e1: 'Elliot', e2: 'Tiago', e3: 'Jamie', e4: 'Aaron', e5: 'Jithin', e6: 'Sofia',
};
const nameOf = (id) => NAMES[id] || null;
const leave = (id, employee, date, scope = 'unavailable', end = null) => ({
  holiday_id: id, employee_id: employee, date, end_date: end, scope,
  label: 'Holiday',
});

let failures = 0;
function check(what, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    console.log(`  ok    ${what}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${what}\n          got      ${a}\n          expected ${e}`);
  }
}

console.log('\nLeave runs\n');

// The case the redesign exists for: the manager saw four rows and could not
// tell it was one holiday.
check('four consecutive single days read as one run',
  buildRuns([
    leave('h1', 'e5', '2026-09-17'), leave('h2', 'e5', '2026-09-18'),
    leave('h3', 'e5', '2026-09-19'), leave('h4', 'e5', '2026-09-20'),
  ], nameOf).map((r) => [r.start, r.end, r.days, r.person, r.entries.length]),
  [['2026-09-17', '2026-09-20', 4, 'Jithin', 4]]);

// ONE ROW PER PERSON. Merging people onto a shared row was the 1a rule and
// the 3a revision reversed it: a row for four people has one Edit button and
// no answer to "whose booking is this".
check('two people off the same days are two rows',
  buildRuns([
    leave('a', 'e1', '2026-09-03', 'unavailable', '2026-09-04'),
    leave('b', 'e3', '2026-09-03', 'unavailable', '2026-09-04'),
  ], nameOf).map((r) => [r.person, r.start, r.end, r.days]),
  [['Elliot', '2026-09-03', '2026-09-04', 2],
   ['Jamie', '2026-09-03', '2026-09-04', 2]]);

check('different people on adjacent days do not join',
  buildRuns([leave('a', 'e1', '2026-09-02'), leave('b', 'e2', '2026-09-03')], nameOf)
    .map((r) => [r.person, r.start, r.end]),
  [['Elliot', '2026-09-02', '2026-09-02'], ['Tiago', '2026-09-03', '2026-09-03']]);

check('a gap breaks a run',
  buildRuns([
    leave('a', 'e5', '2026-09-17'), leave('b', 'e5', '2026-09-18'),
    leave('c', 'e5', '2026-09-21'),
  ], nameOf).map((r) => [r.start, r.end, r.days]),
  [['2026-09-17', '2026-09-18', 2], ['2026-09-21', '2026-09-21', 1]]);

// PAY TYPE DOES NOT BREAK A RUN. This assertion is the exact inverse of the
// one it replaces — paid and unpaid used to be separate rows, and that is
// what made a thirteen-day holiday look like three bookings.
check('paid and unpaid days form ONE absence',
  buildRuns([
    leave('a', 'e5', '2026-09-08', 'unavailable'),
    leave('b', 'e5', '2026-09-09', 'unavailable'),
    leave('c', 'e5', '2026-09-10', 'employee'),
    leave('d', 'e5', '2026-09-11', 'employee'),
    leave('e', 'e5', '2026-09-12', 'unavailable'),
  ], nameOf).map((r) => [r.start, r.end, r.days, r.unpaidDays, r.paidDays]),
  [['2026-09-08', '2026-09-12', 5, 3, 2]]);

check('a mixed run is tagged as one holiday, both counts named',
  buildRuns([
    leave('a', 'e5', '2026-09-08', 'unavailable'),
    leave('b', 'e5', '2026-09-09', 'employee'),
  ], nameOf).map((r) => tagFor(r).label),
  ['Holiday · 1 unpaid + 1 paid']);

check('an all-paid and an all-unpaid run are tagged plainly',
  [
    tagFor(buildRuns([leave('a', 'e1', '2026-09-08', 'employee')], nameOf)[0]).label,
    tagFor(buildRuns([leave('b', 'e1', '2026-09-08', 'unavailable')], nameOf)[0]).label,
  ],
  ['Holiday · paid', 'Holiday · unpaid']);

// Sick is a different KIND of absence, not a different way of paying for
// one, so it is not folded in — "Holiday · 1 unpaid + 1 paid" would describe
// neither half.
check('a sick day next to a holiday stays its own row',
  buildRuns([
    leave('a', 'e6', '2026-09-08', 'unavailable'),
    leave('b', 'e6', '2026-09-09', 'sick'),
  ], nameOf).map((r) => [r.family, r.start, r.days]),
  [['holiday', '2026-09-08', 1], ['sick', '2026-09-09', 1]]);

check('a shop closure spans its range and names nobody',
  buildRuns([leave('s', null, '2026-08-31', 'shop', '2026-09-01')], nameOf)
    .map((r) => [r.start, r.end, r.days, r.family, r.person]),
  [['2026-08-31', '2026-09-01', 2, 'shop', null]]);

check('a range record and an adjacent single day join up',
  buildRuns([
    leave('a', 'e6', '2026-07-20', 'unavailable', '2026-07-24'),
    leave('b', 'e6', '2026-07-25'),
  ], nameOf).map((r) => [r.start, r.end, r.days]),
  [['2026-07-20', '2026-07-25', 6]]);

// The expansion the mixed tag promises: every day, in order, with its own
// pay type.
check('a run keeps its per-day detail for expanding',
  buildRuns([
    leave('a', 'e5', '2026-09-08', 'unavailable'),
    leave('b', 'e5', '2026-09-09', 'employee'),
  ], nameOf)[0].dayScopes,
  [['2026-09-08', 'unavailable'], ['2026-09-09', 'employee']]);

console.log(failures
  ? `\n  ${failures} failed\n`
  : '\n  all passed\n');
process.exit(failures ? 1 : 0);
