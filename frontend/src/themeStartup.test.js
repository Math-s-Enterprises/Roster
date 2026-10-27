jest.mock("react-dom/client", () => ({ createRoot: () => ({ render: jest.fn() }) }));
jest.mock("@/App", () => () => null);
jest.mock("@tanstack/react-query", () => ({ QueryClient: jest.fn(), QueryClientProvider: () => null }));

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

test.each([[null, "light"], ["light", "light"], ["dark", null]])(
  "startup applies saved preference %s before mounting the app", (saved, expected) => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    if (saved) localStorage.setItem("roster_theme", saved);
    const listener = jest.spyOn(document, "addEventListener").mockImplementation(() => {});
    try {
      jest.isolateModules(() => require("./index"));
      expect(document.documentElement.getAttribute("data-theme")).toBe(expected);
    } finally { listener.mockRestore(); }
  },
);
