import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ConfirmDialog from "./ConfirmDialog";

test("confirmation blurs the background, cancels safely and blocks duplicate submits", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  const close = jest.fn();
  let finish;
  const confirm = jest.fn(() => new Promise(resolve => { finish = resolve; }));
  try {
    await act(async () => root.render(<ConfirmDialog title="Remove?" description="Kept until confirmed"
      onClose={close} onConfirm={confirm} />));
    expect(document.querySelector('.backdrop-blur-sm')).not.toBeNull();
    const button = text => [...document.querySelectorAll('[role="alertdialog"] button')]
      .find(b => b.textContent === text);
    await act(async () => button("Cancel").click());
    expect(confirm).not.toHaveBeenCalled();
    close.mockClear();
    await act(async () => button("Remove").click());
    expect(button("Cancel").disabled).toBe(true);
    await act(async () => button("Saving…").click());
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(close).not.toHaveBeenCalled();
    await act(async () => finish(false));
    expect(close).not.toHaveBeenCalled();
    expect(button("Remove").disabled).toBe(false);
  } finally {
    await act(async () => root.unmount()); host.remove();
  }
});
