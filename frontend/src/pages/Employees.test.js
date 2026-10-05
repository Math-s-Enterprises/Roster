import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fs from "fs";
import { DeleteEmployeeDialog } from "./Employees";

jest.mock("react-router-dom", () => ({
  useNavigate: () => () => {},
  useParams: () => ({}),
}), { virtual: true });
jest.mock("@/lib/api", () => ({
  api: {},
  errorMessage: () => "",
  fmtMoney: () => "",
  CURRENCY: "€",
  DAY_SHORT: {},
  DAY_LABELS: {},
  DAYS: [],
  shiftHours: () => 0,
}), { virtual: true });
jest.mock("@/components/ContactImportPanel", () => () => null, { virtual: true });

test("employee deletion uses the app confirmation dialog", () => {
  const html = renderToStaticMarkup(
    <DeleteEmployeeDialog
      employee={{ name: "Teja" }}
      busy={false}
      onClose={() => {}}
      onConfirm={() => {}}
    />,
  );

  expect(html).toContain('role="dialog"');
  expect(html).toContain("Remove Teja?");
  expect(html).toContain("Past rosters are kept.");
  expect(html).toContain("Remove employee");
  expect(fs.readFileSync(require.resolve("./Employees"), "utf8"))
    .not.toContain("window.confirm");
});
