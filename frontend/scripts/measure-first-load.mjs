// Measures per-route "first load JS" from a finished `next build`, the same number the build
// output prints: the gzipped size of every JS chunk the browser must download before the route
// can render. We recompute it from the manifests instead of scraping the build log because the
// log is a human-formatted table that Next reformats between releases.
import { readFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

// Level 9 is what Next's own size reporting uses; matching it keeps our numbers comparable to
// the table developers already look at.
const GZIP_LEVEL = 9;

/** Entry points that are compiler plumbing, not routes anyone navigates to. */
const PAGES_INTERNALS = new Set(["/_app", "/_document", "/_error"]);

class BuildOutputError extends Error {}

function readManifest(distDir, name, { required = true } = {}) {
  const path = join(distDir, name);
  if (!existsSync(path)) {
    if (!required) return null;
    throw new BuildOutputError(
      `${path} not found — run \`npm run build\` before checking the perf budget.`,
    );
  }
  return JSON.parse(readFileSync(path, "utf8"));
}

/** Gzipped byte size of one emitted chunk, memoised: shared chunks appear on every route. */
function sizer(distDir) {
  const cache = new Map();
  return (file) => {
    let size = cache.get(file);
    if (size === undefined) {
      const path = join(distDir, file);
      if (!existsSync(path)) {
        throw new BuildOutputError(`${path} is listed in a build manifest but missing on disk.`);
      }
      size = gzipSync(readFileSync(path), { level: GZIP_LEVEL }).length;
      cache.set(file, size);
    }
    return size;
  };
}

function sumUnique(files, sizeOf) {
  return [...new Set(files)].reduce((total, file) => total + sizeOf(file), 0);
}

/**
 * @returns {{routes: Record<string, number>, shared: number}} byte counts, keyed by public route.
 */
export function measureFirstLoad(distDir) {
  const sizeOf = sizer(distDir);
  const routes = {};
  const appPageChunks = [];

  // App router: app-build-manifest maps internal entries ("/traces/page") to their chunks, and
  // app-path-routes-manifest translates those entries to public paths. Going through the second
  // manifest also drops layouts, error boundaries and other non-navigable entries for free.
  const appChunks = readManifest(distDir, "app-build-manifest.json", { required: false });
  const appRoutes = readManifest(distDir, "app-path-routes-manifest.json", { required: false });
  if (appChunks && appRoutes) {
    for (const [entry, route] of Object.entries(appRoutes)) {
      // Route handlers (`/route`) render on the server and ship no client bundle; the chunks the
      // manifest lists for them are the shared baseline, which `shared` already covers.
      if (!entry.endsWith("/page")) continue;
      const files = appChunks.pages[entry] ?? [];
      appPageChunks.push([...new Set(files)]);
      routes[route] = sumUnique(files, sizeOf);
    }
  }

  // Pages router: every page also loads the polyfills and the _app entry.
  const pagesChunks = readManifest(distDir, "build-manifest.json");
  const pagesBase = [...(pagesChunks.polyfillFiles ?? []), ...(pagesChunks.pages["/_app"] ?? [])];
  for (const [route, files] of Object.entries(pagesChunks.pages)) {
    if (PAGES_INTERNALS.has(route)) continue;
    routes[route] = sumUnique([...pagesBase, ...files], sizeOf);
  }

  // A failed or half-written build leaves manifests behind with no entries. Without this the
  // gate would "pass" by measuring nothing, which is the one failure mode a budget must not have.
  if (Object.keys(routes).length === 0) {
    throw new BuildOutputError(
      `${distDir} contains no routes — the build did not finish. Re-run \`npm run build\`.`,
    );
  }

  return { routes, shared: measureShared(appPageChunks, sizeOf) };
}

/**
 * The baseline every app-router page pays: the chunks common to all of them. Budgeting it
 * separately is what catches a heavy dependency pulled into the root layout, which otherwise
 * shows up as a diffuse few-kB rise on twenty routes and no single obvious culprit.
 */
function measureShared(appPageChunks, sizeOf) {
  if (appPageChunks.length === 0) return 0;
  const common = appPageChunks.reduce((acc, files) => acc.filter((f) => files.includes(f)));
  return sumUnique(common, sizeOf);
}

export { BuildOutputError };
