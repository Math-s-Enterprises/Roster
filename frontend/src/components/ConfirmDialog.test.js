import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { ConfirmProvider, useConfirm } from "./ConfirmDialog";

// React only flushes updates synchronously inside act() when told it is in a
// test. Without this every assertion below would race the render.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const OPTIONS = {
  title: "Remove Deli?",
  body: "This takes the roster group off the list.",
  detail: "Only if nothing uses it.",
  confirmLabel: "Remove group",
  cancelLabel: "Keep it",
};

let host;
let root;
let confirm;

function Grab() {
  confirm = useConfirm();
  return null;
}

async function mount(withProvider = true) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(withProvider ? <ConfirmProvider><Grab /></ConfirmProvider> : <Grab />);
  });
}

afterEach(async () => {
  // Unmounting also answers any prompt a test left open, so none hangs.
  await act(async () => { root?.unmount(); });
  host?.remove();
  root = undefined;
  host = undefined;
  document.body.style.overflow = "";
  jest.restoreAllMocks();
});

const dialog = () => document.querySelector('[role="alertdialog"]');
const scrim = () => document.querySelector(".cf-scrim");
const button = (label) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent === label);

/**
 * Open a prompt. Returns its promise *without* waiting for it — the promise
 * only settles when somebody answers, so awaiting it here would hang.
 */
async function open(options = OPTIONS) {
  const opened = {};
  await act(async () => { opened.promise = confirm(options); });
  return opened;
}

async function press(key, init = {}) {
  await act(async () => {
    document.activeElement.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
    );
  });
}

async function click(element) {
  await act(async () => { element.click(); });
}

async function mouse(target, type) {
  await act(async () => { target.dispatchEvent(new MouseEvent(type, { bubbles: true })); });
}

test("shows the title, body and detail, labelled for assistive technology", async () => {
  await mount();
  await open();
  const box = dialog();
  expect(box).not.toBeNull();
  expect(box.getAttribute("aria-modal")).toBe("true");
  expect(document.getElementById(box.getAttribute("aria-labelledby")).textContent)
    .toBe("Remove Deli?");
  const described = document.getElementById(box.getAttribute("aria-describedby"));
  expect(described.textContent).toContain("takes the roster group off the list");
  expect(described.textContent).toContain("Only if nothing uses it");
});

test("a destructive prompt focuses Cancel, so a stray Enter does nothing", async () => {
  await mount();
  await open();
  expect(document.activeElement).toBe(button("Keep it"));
});

test("a non-destructive prompt focuses the confirm button", async () => {
  await mount();
  await open({ ...OPTIONS, tone: "default" });
  expect(document.activeElement).toBe(button("Remove group"));
});

test("the confirm button answers true and closes the dialog", async () => {
  await mount();
  const { promise } = await open();
  await click(button("Remove group"));
  await expect(promise).resolves.toBe(true);
  expect(dialog()).toBeNull();
});

test("the cancel button answers false and closes the dialog", async () => {
  await mount();
  const { promise } = await open();
  await click(button("Keep it"));
  await expect(promise).resolves.toBe(false);
  expect(dialog()).toBeNull();
});

test("Escape answers false and gives focus back to what opened it", async () => {
  await mount();
  const opener = document.createElement("button");
  opener.textContent = "opener";
  document.body.appendChild(opener);
  opener.focus();

  const { promise } = await open();
  expect(document.activeElement).not.toBe(opener);

  await press("Escape");
  await expect(promise).resolves.toBe(false);
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

test("leaves focus alone when the element that opened it has been removed", async () => {
  await mount();
  const opener = document.createElement("button");
  document.body.appendChild(opener);
  opener.focus();

  const { promise } = await open();
  opener.remove(); // the row it belonged to is gone
  await click(button("Remove group"));
  await expect(promise).resolves.toBe(true);
  expect(dialog()).toBeNull(); // and nothing threw
});

test("clicking the backdrop cancels", async () => {
  await mount();
  const { promise } = await open();
  await mouse(scrim(), "mousedown");
  await mouse(scrim(), "click");
  await expect(promise).resolves.toBe(false);
});

test("clicking inside the dialog does not cancel it", async () => {
  await mount();
  await open();
  await mouse(dialog(), "mousedown");
  await mouse(dialog(), "click");
  expect(dialog()).not.toBeNull();
});

test("a drag that starts inside the dialog and ends on the backdrop does not cancel it", async () => {
  await mount();
  await open();
  await mouse(dialog(), "mousedown");
  await mouse(scrim(), "click");
  expect(dialog()).not.toBeNull();
});

test("Tab wraps from the last button to the first, and Shift+Tab back", async () => {
  await mount();
  await open();
  expect(document.activeElement).toBe(button("Keep it")); // last in the DOM

  await press("Tab");
  expect(document.activeElement).toBe(button("Remove group"));

  await press("Tab", { shiftKey: true });
  expect(document.activeElement).toBe(button("Keep it"));
});

test("Tab brings focus back in if it has landed on the dialog itself", async () => {
  await mount();
  await open();
  await act(async () => { dialog().focus(); });
  expect(document.activeElement).toBe(dialog());
  await press("Tab");
  expect(document.activeElement).toBe(button("Remove group"));
});

test("a second prompt cancels the first rather than leaving it hanging", async () => {
  await mount();
  const first = await open();
  const second = await open({ ...OPTIONS, title: "Remove Kitchen?" });

  await expect(first.promise).resolves.toBe(false);
  expect(document.querySelectorAll('[role="alertdialog"]')).toHaveLength(1);
  expect(document.querySelector(".cf-title").textContent).toBe("Remove Kitchen?");

  await click(button("Remove group"));
  await expect(second.promise).resolves.toBe(true);
});

test("background scroll is locked while open and restored after", async () => {
  await mount();
  document.body.style.overflow = "auto";
  const { promise } = await open();
  expect(document.body.style.overflow).toBe("hidden");
  await click(button("Keep it"));
  await promise;
  expect(document.body.style.overflow).toBe("auto");
});

test("unmounting while a prompt is open answers false instead of hanging", async () => {
  await mount();
  const { promise } = await open();
  await act(async () => { root.unmount(); });
  await expect(promise).resolves.toBe(false);
  root = createRoot(host); // so afterEach has something to unmount
});

test("without a provider it falls back to the native confirm, passing the text through", async () => {
  await mount(false);
  const native = jest.spyOn(window, "confirm").mockReturnValue(true);

  await expect(confirm(OPTIONS)).resolves.toBe(true);
  expect(native).toHaveBeenCalledTimes(1);
  expect(native.mock.calls[0][0]).toContain("Remove Deli?");
  expect(native.mock.calls[0][0]).toContain("Only if nothing uses it");

  native.mockReturnValue(false);
  await expect(confirm(OPTIONS)).resolves.toBe(false);
});
