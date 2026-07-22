#!/usr/bin/env node
// Gates first-load JS against frontend/perf-budget.json. Bundle regressions are invisible in a
// diff — a one-line import can add 80 kB to every page — so CI measures the built output and
// fails the job instead of letting it land and be discovered months later in a field report.
//
//   node scripts/bundle-budget.mjs                 # check (exit 1 when over budget)
//   node scripts/bundle-budget.mjs --update        # rewrite the budget from what was measured
//   node scripts/bundle-budget.mjs --dist .next-build
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { measureFirstLoad, BuildOutputError } from "./measure-first-load.mjs";

const FRONTEND_DIR = dirname(dirname(fileURLToPath(import.meta.url)));
const BUDGET_FILE = join(FRONTEND_DIR, "perf-budget.json");

const args = process.argv.slice(2);
const update = args.includes("--update");
const distArg = args.indexOf("--dist");
// Mirrors next.config.js, so `NEXT_BUILD_DIR=.next-build next build` can be checked as-is.
const distDir = resolve(
  FRONTEND_DIR,
  distArg !== -1 ? args[distArg + 1] : process.env.NEXT_BUILD_DIR || ".next",
);

const kb = (bytes) => bytes / 1000;
const fmt = (bytes) => `${kb(bytes).toFixed(1)} kB`;

/** Headroom for the noise floor (minifier churn, zlib version drift) without hiding a real jump. */
function budgetFor(bytes) {
  return Math.max(Math.ceil(kb(bytes) * 1.1), Math.ceil(kb(bytes)) + 5);
}

function main() {
  const budget = JSON.parse(readFileSync(BUDGET_FILE, "utf8"));
  const measured = measureFirstLoad(distDir);

  if (update) return writeBudget(budget, measured);

  const rows = [
    { name: "(shared by all)", bytes: measured.shared, limitKb: budget.sharedKb, explicit: true },
    ...Object.entries(measured.routes)
      .map(([route, bytes]) => ({
        name: route,
        bytes,
        limitKb: budget.routes[route] ?? budget.defaultRouteKb,
        explicit: route in budget.routes,
      }))
      .sort((a, b) => b.bytes - a.bytes),
  ];

  const width = Math.max(...rows.map((r) => r.name.length));
  console.log(`first-load JS (gzip) from ${distDir}\n`);
  for (const row of rows) {
    const over = kb(row.bytes) > row.limitKb;
    const note = row.explicit ? "" : "  (no explicit budget — using defaultRouteKb)";
    console.log(
      `${over ? "FAIL" : "ok  "}  ${row.name.padEnd(width)}  ${fmt(row.bytes).padStart(9)}` +
        `  / ${String(row.limitKb).padStart(4)} kB${note}`,
    );
  }

  for (const route of Object.keys(budget.routes)) {
    if (!(route in measured.routes)) {
      console.log(`\nwarning: perf-budget.json still budgets ${route}, which the build no longer emits.`);
    }
  }

  const failures = rows.filter((r) => kb(r.bytes) > r.limitKb);
  if (failures.length === 0) {
    console.log("\nAll routes within budget.");
    return;
  }
  console.error(
    `\n${failures.length} entr${failures.length === 1 ? "y" : "ies"} over budget. Either trim the ` +
      `bundle (dynamic import, drop the dependency) or, if the growth is justified, raise the ` +
      `number in frontend/perf-budget.json in the same PR so the increase is reviewed.`,
  );
  process.exitCode = 1;
}

function writeBudget(budget, measured) {
  const routes = {};
  for (const route of Object.keys(measured.routes).sort()) {
    routes[route] = budgetFor(measured.routes[route]);
  }
  const next = { ...budget, sharedKb: budgetFor(measured.shared), routes };
  writeFileSync(BUDGET_FILE, `${JSON.stringify(next, null, 2)}\n`);
  console.log(`Rewrote ${BUDGET_FILE} from ${distDir}.`);
}

try {
  main();
} catch (err) {
  if (!(err instanceof BuildOutputError)) throw err;
  console.error(err.message);
  process.exitCode = 1;
}
