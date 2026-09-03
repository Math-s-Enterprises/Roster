#!/usr/bin/env node
/**
 * Consecutive leave days collapse into one run, and unrelated days do not.
 *
 *     node check-leave-runs.js
 *
 * WHY THIS EXISTS
 * ---------------
 * `buildRuns` in pages/CalendarPage.js is the whole point of the Holidays
 * redesign. The old page rendered four consecutive single-day records for one
 * person as four identical rows, which is why nobody could tell how long
 * anybody was actually off. Two collapses fix that, and they pull in opposite
 * directions:
 *
 *   1. ADJACENT DAYS for one person and type become one run.
 *   2. RUNS OF THE SAME SHAPE merge their people onto one row.
 *
 * Rule 2 applied first would glue different people's unrelated dates
 * together — Elliot off Wednesday and Tiago off Thursday would read as one
 * two-day booking for both of them. Neither rule is safe alone and the order
 * is not obvious from reading either one, so it is pinned here.
 *
 * There is no jest setup in this app, and a production build needs more
 * memory than a sandbox usually has. This runs in plain node in about a
 * second, in the same spirit as check-css-vars.js: the cheapest thing that
 * would actually have caught the bug.
 *
 * Sabotage-checked. Dropping the type from the run key, merging by shape
 * only, and ignoring adjacency each fail a different case below.
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

const { buildRuns } = loadPage();

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
  ], nameOf).map((r) => [r.start, r.end, r.days, r.people.join(', '), r.entries.length]),
  [['2026-09-17', '2026-09-20', 4, 'Jithin', 4]]);

check('four people off the same day read as one row',
  buildRuns([
    leave('a', 'e1', '2026-09-02'), leave('b', 'e2', '2026-09-02'),
    leave('c', 'e3', '2026-09-02'), leave('d', 'e4', '2026-09-02'),
  ], nameOf).map((r) => [r.start, r.days, r.people.join(', ')]),
  [['2026-09-02', 1, 'Elliot, Tiago, Jamie, Aaron']]);

// The two collapses must not be confused with each other.
check('different people on adjacent days stay apart',
  buildRuns([leave('a', 'e1', '2026-09-02'), leave('b', 'e2', '2026-09-03')], nameOf)
    .map((r) => [r.start, r.end, r.people.join(', ')]),
  [['2026-09-02', '2026-09-02', 'Elliot'], ['2026-09-03', '2026-09-03', 'Tiago']]);

check('a gap breaks a run',
  buildRuns([
    leave('a', 'e5', '2026-09-17'), leave('b', 'e5', '2026-09-18'),
    leave('c', 'e5', '2026-09-21'),
  ], nameOf).map((r) => [r.start, r.end, r.days]),
  [['2026-09-17', '2026-09-18', 2], ['2026-09-21', '2026-09-21', 1]]);

// Paid and unpaid are different things to a payroll and must stay separate,
// even back to back for one person.
check('paid and unpaid leave do not merge',
  buildRuns([
    leave('a', 'e1', '2026-09-02', 'employee'),
    leave('b', 'e1', '2026-09-03', 'unavailable'),
  ], nameOf).map((r) => [r.scope, r.days]),
  [['employee', 1], ['unavailable', 1]]);

check('a shop closure spans its range and names nobody',
  buildRuns([leave('s', null, '2026-08-31', 'shop', '2026-09-01')], nameOf)
    .map((r) => [r.start, r.end, r.days, r.scope, r.people.length]),
  [['2026-08-31', '2026-09-01', 2, 'shop', 0]]);

check('a range record and an adjacent single day join up',
  buildRuns([
    leave('a', 'e6', '2026-07-20', 'unavailable', '2026-07-24'),
    leave('b', 'e6', '2026-07-25'),
  ], nameOf).map((r) => [r.start, r.end, r.days]),
  [['2026-07-20', '2026-07-25', 6]]);

console.log(failures
  ? `\n  ${failures} failed\n`
  : '\n  all passed\n');
process.exit(failures ? 1 : 0);
