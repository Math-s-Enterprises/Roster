import { CONSENT_KEY, initializeConsent, readConsent, readPreference, saveConsent, writePreference } from "./cookieConsent";

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); initializeConsent(); });
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); localStorage.clear(); initializeConsent(); });

test("preference choices work in memory before consent and only persist after opt-in", () => {
  writePreference("roster_theme", "dark");
  expect(readPreference("roster_theme")).toBe("dark");
  expect(localStorage.getItem("roster_theme")).toBeNull();
  saveConsent({ preferences: true });
  expect(localStorage.getItem("roster_theme")).toBe("dark");
  expect(readConsent()).toMatchObject({ preferences: true, fonts: false, google: false });
  initializeConsent();
  expect(readPreference("roster_theme")).toBe("dark");
});

test("rejection removes only optional data, preserving authentication, security and roster context", () => {
  localStorage.setItem("roster_token", "fictional-session");
  localStorage.setItem("roster_group", "Deli");
  localStorage.setItem("roster_login_guard", "security-counter");
  localStorage.setItem("unrelated_app_setting", "keep");
  for (const key of ["roster_theme", "roster_fixed_shifts_view", "roster_hours_sort", "roster_learning_sort", "roster_notifications:one"]) {
    localStorage.setItem(key, "old-value"); sessionStorage.setItem(key, "old-value");
  }
  saveConsent({});
  expect(localStorage.getItem("roster_theme")).toBeNull();
  expect(localStorage.getItem("roster_notifications:one")).toBeNull();
  expect(sessionStorage.getItem("roster_notifications:one")).toBeNull();
  expect(localStorage.getItem("roster_fixed_shifts_view")).toBeNull();
  expect(localStorage.getItem("roster_hours_sort")).toBeNull();
  expect(localStorage.getItem("roster_learning_sort")).toBeNull();
  expect(localStorage.getItem("roster_token")).toBe("fictional-session");
  expect(localStorage.getItem("roster_group")).toBe("Deli");
  expect(localStorage.getItem("roster_login_guard")).toBe("security-counter");
  expect(localStorage.getItem("unrelated_app_setting")).toBe("keep");
});

test("old Got it acknowledgements are not upgraded to consent", () => {
  localStorage.setItem("roster_cookie_notice", "acknowledged");
  localStorage.setItem("roster_theme", "dark");
  initializeConsent();
  expect(readConsent()).toBeNull();
  expect(readPreference("roster_theme")).toBeNull();
  expect(localStorage.getItem("roster_cookie_notice")).toBeNull();
});

test("a failed withdrawal write removes the old permission rather than reusing it after reload", () => {
  saveConsent({ preferences: true, fonts: true, google: true });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
  saveConsent({});
  expect(readConsent()).toMatchObject({ preferences: false, fonts: false, google: false });
  expect(localStorage.getItem(CONSENT_KEY)).toBeNull();
  initializeConsent();
  expect(readConsent()).toBeNull();
});

test("choices expire after 180 days and must be made again", () => {
  jest.useFakeTimers(); jest.setSystemTime(new Date("2026-11-05T12:00:00Z"));
  saveConsent({ preferences: true, fonts: true, google: true });
  writePreference("roster_theme", "dark");
  expect(readConsent().expiresAt - readConsent().decidedAt).toBe(180 * 86400000);
  jest.setSystemTime(new Date("2027-05-05T12:00:00Z"));
  expect(readConsent()).toBeNull();
  initializeConsent();
  expect(localStorage.getItem("roster_theme")).toBeNull();
});

test.each(["bad json", '{"version":99}', '{"version":1,"preferences":"true"}'])("malformed or obsolete consent defaults to off: %s", value => {
  localStorage.setItem(CONSENT_KEY, value);
  expect(readConsent()).toBeNull();
});
