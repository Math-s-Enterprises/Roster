import fs from "fs";
import path from "path";

test("the app does not load Emergent scripts or analytics", () => {
  const html = fs.readFileSync(path.join(process.cwd(), "public/index.html"), "utf8");
  expect(html.toLowerCase()).not.toMatch(/emergent|posthog/);
  expect(html).toContain('<div id="root"></div>');
});
