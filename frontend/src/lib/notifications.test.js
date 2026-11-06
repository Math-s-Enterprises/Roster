import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { NotificationsProvider, useNotifications } from "./notifications";
import { initializeConsent, saveConsent } from "./cookieConsent";

let mockToasts = [];
jest.mock("sonner", () => ({ useSonner: () => ({ toasts: mockToasts }) }));
function List() {
  const { items } = useNotifications();
  return <div>{items.map(item => <span key={item.id}>{item.message}</span>)}</div>;
}

test("notifications stay in memory until allowed and saved copies are removed on withdrawal", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); initializeConsent();
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  const render = () => root.render(<NotificationsProvider userId="fictional-user"><List /></NotificationsProvider>);
  try {
    await act(async () => render());
    mockToasts = [{ id: "one", type: "success", title: "Fictional notification" }];
    await act(async () => render());
    expect(host.textContent).toContain("Fictional notification");
    expect(localStorage.getItem("roster_notifications:fictional-user")).toBeNull();
    await act(async () => saveConsent({ preferences: true }));
    expect(JSON.parse(localStorage.getItem("roster_notifications:fictional-user")).items).toHaveLength(1);
    await act(async () => saveConsent({}));
    expect(localStorage.getItem("roster_notifications:fictional-user")).toBeNull();
    expect(host.textContent).toContain("Fictional notification");
    mockToasts = [];
    await act(async () => root.render(null));
    await act(async () => render());
    expect(host.textContent).toBe("");
  } finally { await act(async () => root.unmount()); host.remove(); mockToasts = []; localStorage.clear(); initializeConsent(); }
});
