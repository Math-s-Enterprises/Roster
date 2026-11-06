import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fs from "fs";
import path from "path";
import postcss from "postcss";
import RosterPrintSheet from "./RosterPrintSheet";

let style;
beforeEach(() => {
  const printRules = [];
  postcss.parse(fs.readFileSync(path.join(process.cwd(), "src/index.css"), "utf8"))
    .walkAtRules("media", media => {
      if (media.params === "print") media.each(node => { if (node.type === "rule") printRules.push(node.toString()); });
    });
  style = document.createElement("style");
  style.textContent = ".nv-burger { display: flex; }\n" + printRules.join("\n");
  document.head.appendChild(style);
});
afterEach(() => { style.remove(); document.body.innerHTML = ""; });

test("printing keeps the roster table and hides navigation and extension overlays outside the sheet", () => {
  const sheet = renderToStaticMarkup(<RosterPrintSheet
    shop={{ name: "Fictional Shop" }}
    roster={{ week_start: "2099-01-05", shifts: [{ employee_id: "one", day: "mon", start: "09:00", end: "17:00" }] }}
    employees={[{ employee_id: "one", name: "Test Person", role: "Crew" }]}
  />);
  document.body.innerHTML = `<div id="root"><div class="nv-shell">
    <button class="nv-burger">Menu</button><aside>Navigation</aside>
    <main class="nv-main"><div class="wr-page"><header>Screen controls</header>${sheet}
    <div id="nested-overlay" style="position:fixed">Extension overlay</div></div></main>
    <div id="app-overlay">Another overlay</div></div></div>
    <div id="extension-host" style="position:fixed"><iframe title="Extension"></iframe></div>`;
  for (const selector of [".nv-burger", "aside", "header", "#nested-overlay", "#app-overlay", "#extension-host"]) {
    expect(getComputedStyle(document.querySelector(selector)).display).toBe("none");
  }
  let node = document.querySelector(".print-table td");
  while (node && node !== document.body) {
    expect(getComputedStyle(node).display).not.toBe("none");
    node = node.parentElement;
  }
  expect(document.querySelector("#print-sheet").textContent).toContain("Test Person");
  expect(document.querySelector("#print-sheet").textContent).toContain("09:00–17:00");
  expect(getComputedStyle(document.querySelector(".wr-page")).backgroundColor).toBe("rgb(255, 255, 255)");
  const lateOverlay = document.createElement("div");
  lateOverlay.textContent = "Injected after page load"; document.body.appendChild(lateOverlay);
  expect(getComputedStyle(lateOverlay).display).toBe("none");
});

test("printing a page without a roster sheet does not blank out the app", () => {
  document.body.innerHTML = '<div id="root"><main><h1>Ordinary page</h1></main></div>';
  for (const node of document.querySelectorAll("#root, main, h1")) {
    expect(getComputedStyle(node).display).not.toBe("none");
  }
});
