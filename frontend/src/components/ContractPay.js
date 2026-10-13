import React, { useId } from "react";
import { CURRENCY } from "@/lib/api";

/**
 * Contract pay: a weekly or a monthly salary for a full-time contract.
 *
 * A salaried contract is paid one fixed amount, so the form asks for it the way a
 * contract states it - which of the two, and how much - instead of an hourly rate.
 * The server works the hourly rate out from it (services/contract_pay.py), because
 * every cost in the app is hours x rate. The sums here MUST match the server's;
 * they are only used to show the person what their figure will mean before they
 * save it. The server's answer is the one that counts.
 *
 *   weekly pay  = the weekly salary, or the monthly salary x 12 / 52
 *   hourly rate = weekly pay / contracted weekly hours
 *
 * A month is 52/12 weeks, not four: four would overstate the weekly cost of
 * everyone on a monthly salary by about 8%.
 */

export const CONTRACT_PAY_PERIODS = [
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
];

const WEEKS_PER_YEAR = 52;
const MONTHS_PER_YEAR = 12;

/** What the salary comes to in a week; null if either part is missing or not a sum. */
export function weeklyEquivalent(period, salary) {
  const amount = Number(salary);
  if (salary === "" || salary == null || !Number.isFinite(amount) || amount <= 0) return null;
  if (period === "weekly") return amount;
  if (period === "monthly") return (amount * MONTHS_PER_YEAR) / WEEKS_PER_YEAR;
  return null;
}

/** The hourly rate that makes a full contracted week cost exactly the salary. */
export function hourlyEquivalent(period, salary, paidHours) {
  const weekly = weeklyEquivalent(period, salary);
  const hours = Number(paidHours);
  if (weekly == null || !Number.isFinite(hours) || hours <= 0) return null;
  return weekly / hours;
}

const group = (amount, decimals) => Number(amount).toLocaleString("en-IE", {
  minimumFractionDigits: decimals, maximumFractionDigits: decimals,
});

/** A salary as written on a contract: 3,000 with no pence, 2,999.99 with. */
export function fmtSalary(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return `${CURRENCY}0`;
  return `${CURRENCY}${group(n, Number.isInteger(n) ? 0 : 2)}`;
}

/** A worked-out figure: always pence, so 700 reads as 700.00 beside 692.31. */
const fmtDerived = (amount) => `${CURRENCY}${group(amount, 2)}`;

/** The label and value for an employee's pay tile, or null when they have no salary. */
export function salaryTile(employee) {
  if (!employee || !employee.contract_pay_period || !(Number(employee.contract_salary) > 0)) return null;
  return {
    label: employee.contract_pay_period === "monthly" ? "Monthly salary" : "Weekly salary",
    value: fmtSalary(employee.contract_salary),
  };
}

export default function ContractPay({ period, salary, paidHours, onChange }) {
  const helpId = useId();
  const chosen = CONTRACT_PAY_PERIODS.find((p) => p.key === period);
  const weekly = weeklyEquivalent(period, salary);
  const hourly = hourlyEquivalent(period, salary, paidHours);

  const label = chosen ? `${chosen.label} salary (${CURRENCY})` : `Salary (${CURRENCY})`;

  let help;
  if (!chosen) {
    help = "Choose weekly or monthly, then enter the salary.";
  } else if (weekly == null) {
    help = `Enter the ${chosen.key} salary.`;
  } else if (hourly == null) {
    help = `That is ${fmtDerived(weekly)} a week. Set the contracted weekly hours above so the cost can be worked out.`;
  } else {
    help = `That is ${fmtDerived(weekly)} a week. Costed at ${fmtDerived(hourly)} an hour `
      + `(weekly pay ÷ ${Number(paidHours)} contracted hours), so a full contracted week costs exactly the salary.`;
  }

  return (
    <fieldset className="col-span-2 space-y-2 min-w-0" data-testid="contract-pay" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="text-[11px] esp-ink-mute mb-1 p-0">Contract pay</legend>
      <div className="flex items-center gap-5">
        {CONTRACT_PAY_PERIODS.map((p) => (
          <label key={p.key} className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="radio"
              name="contract_pay_period"
              value={p.key}
              data-testid={`emp-pay-${p.key}`}
              checked={period === p.key}
              onChange={() => onChange({ contract_pay_period: p.key })}
              required
              className="shrink-0"
              style={{ minHeight: 0, accentColor: "var(--primary)" }}
            />
            {p.label}
          </label>
        ))}
      </div>
      <label className="block">
        <div className="text-[11px] esp-ink-mute mb-1">{label}</div>
        <input
          data-testid="emp-salary"
          type="number"
          inputMode="decimal"
          min="0.01"
          max="1000000"
          step="0.01"
          required
          value={salary}
          onChange={(e) => onChange({ contract_salary: e.target.value })}
          placeholder={period === "weekly" ? "e.g. 700" : "e.g. 3000"}
          aria-describedby={helpId}
          className="w-full px-3 py-2.5 rounded-lg font-mono"
        />
      </label>
      <p id={helpId} className="text-[11px]" data-testid="contract-pay-help" style={{ color: "var(--ink-mute-2)" }}>
        {help}
      </p>
    </fieldset>
  );
}
