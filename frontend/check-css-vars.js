#!/usr/bin/env node
/**
 * Every CSS variable the code uses must exist, and must be a colour.
 *
 *     node check-css-vars.js
 *
 * WHY THIS EXISTS
 * ---------------
 * Two bugs shipped and survived several sessions because CSS fails SILENTLY.
 * An invalid declaration is dropped by the browser — no console error, no
 * fallback, no visual placeholder. You get an element with no background, and
 * nothing anywhere says why.
 *
 *   1. `background: var(--good)`   — --good was never defined. Anywhere.
 *   2. `background: var(--accent)` — --accent IS defined, but only inside the
 *      shadcn @layer block, where it holds a bare HSL TRIPLET ("0 0% 15%")
 *      meant to be written hsl(var(--accent)). Used raw it is not a colour.
 *
 * Both were in the edit-trend chart on the What It Learned page, which meant
 * every bar in it rendered with no fill — the one screen whose entire job is
 * showing a number going down.
 *
 * The second is the nastier of the two, because grepping for "is it defined"
 * says yes. The check that catches it is "is it defined as something you can
 * put after `color:`".
 *
 * Exits non-zero on a problem so it can go in CI later.
 */
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "src");
const CSS = path.join(SRC, "index.css");

// Tokens declared inside the shadcn `@layer base` block are HSL triplets by
// convention and are only ever legal wrapped in hsl(). Listed explicitly
// rather than detected, so that adding one to the wrong block is caught too.
const TRIPLET_ONLY = new Set([
  "background", "foreground", "card", "card-foreground", "popover",
  "popover-foreground", "secondary", "secondary-foreground", "muted",
  "muted-foreground", "accent", "accent-foreground", "destructive",
  "destructive-foreground", "border", "input", "ring",
]);

/**
 * Variables set at RUNTIME rather than in the stylesheet, so "not declared in
 * index.css" is correct for them and not a bug.
 *
 *   --radix-*  Radix UI writes these onto the element from JS (popover height,
 *              trigger width, swipe distance) before the CSS that reads them
 *              ever applies. Seven of these were the check's first output, and
 *              a check that reports seven false alarms gets ignored, which is
 *              worse than not having one.
 *   --print-*  set inline by the print dialog, and always written with a
 *              fallback anyway.
 */
const RUNTIME_PREFIXES = ["radix-", "print-"];

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return /\.(js|jsx|css)$/.test(entry.name) ? [full] : [];
  });

const css = fs.readFileSync(CSS, "utf8");
const defined = new Set(
  [...css.matchAll(/^\s*--([a-z0-9-]+)\s*:/gim)].map((m) => m[1]),
);

const problems = [];
for (const file of walk(SRC)) {
  const text = fs.readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    // Comments explain these bugs by name; they are not usages.
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
    for (const m of line.matchAll(/var\(\s*--([a-z0-9-]+)\s*([,)])/g)) {
      const [, name, next] = m;
      const hasFallback = next === ",";
      const where = `${path.relative(__dirname, file)}:${i + 1}`;
      if (RUNTIME_PREFIXES.some((p) => name.startsWith(p))) continue;
      if (!defined.has(name) && !hasFallback) {
        problems.push(`${where}\n    var(--${name}) is never defined — the `
          + `declaration is dropped and nothing renders.`);
      } else if (TRIPLET_ONLY.has(name) && !/hsl\(\s*var\(\s*--/.test(line)) {
        problems.push(`${where}\n    var(--${name}) is a shadcn HSL triplet, `
          + `not a colour. Write hsl(var(--${name})) — or use a semantic `
          + `token like --primary / --ink-mute.`);
      }
    }
  });
}

if (problems.length) {
  console.error(`\n${problems.length} CSS variable problem(s) — each one is `
    + `INVISIBLE at runtime:\n`);
  problems.forEach((p) => console.error("  " + p + "\n"));
  process.exit(1);
}
console.log(`CSS variables OK — ${defined.size} defined, all usages valid.`);
