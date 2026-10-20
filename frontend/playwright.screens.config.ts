import { mkdtempSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"

/**
 * Screenshot comparison suite: every page, viewer, menu and main dialog, compared
 * pixel for pixel against snapshots recorded earlier. See tests/e2e/screens/README.md.
 *
 *   npx playwright test --config=playwright.screens.config.ts [--update-snapshots]
 *
 * The specs and this config always come from this tree. The servers can come from
 * another checkout of the repository, so one tree's suite can record snapshots from
 * another tree's app:
 *
 *   XRAYLARCH_SCREENS_APP_ROOT     repository whose backend/.venv and frontend/ serve the
 *                                  app (default: this repository)
 *   XRAYLARCH_SCREENS_SNAPSHOT_DIR where the snapshots live (default:
 *                                  frontend/test-results/screens-snapshots, not committed)
 *   XRAYLARCH_SCREENS_BACKEND_PORT / _FRONTEND_PORT / _MOUNT_PORT
 *                                  (default 18306 / 13304 / frontend + 1), so the suite can
 *                                  run beside the normal E2E servers
 *   XRAYLARCH_SCREENS_REUSE_SERVERS=1
 *                                  use servers already listening on those ports (for
 *                                  writing specs only; a recorded or compared run starts
 *                                  its own)
 */
const frontendRoot = fileURLToPath(new URL(".", import.meta.url))
const appRoot = path.resolve(process.env.XRAYLARCH_SCREENS_APP_ROOT ?? path.resolve(frontendRoot, ".."))
const appFrontend = path.join(appRoot, "frontend")
const snapshotDir = path.resolve(process.env.XRAYLARCH_SCREENS_SNAPSHOT_DIR ?? path.join(frontendRoot, "test-results", "screens-snapshots"))
const dataRoot = mkdtempSync(path.join(os.tmpdir(), "xraylarch-web-screens-"))
process.env.XRAYLARCH_E2E_DATA_ROOT_INTERNAL = dataRoot

const backendPort = process.env.XRAYLARCH_SCREENS_BACKEND_PORT ?? "18306"
const frontendPort = process.env.XRAYLARCH_SCREENS_FRONTEND_PORT ?? "13304"
const mountPort = process.env.XRAYLARCH_SCREENS_MOUNT_PORT ?? String(Number(frontendPort) + 1)
const appBasePath = "/advanced-xas/app"
const backendOrigin = `http://127.0.0.1:${backendPort}`
const reuseExistingServer =process.env.XRAYLARCH_SCREENS_REUSE_SERVERS === "1"

const backendEnv = {
  XRAYLARCH_DATA_ROOT: dataRoot,
  XRAYLARCH_INTEGRATION_API_ENABLED: "true",
  XRAYLARCH_BROWSER_CONSUME_ENABLED: "true",
  XRAYLARCH_IMPORT_ENABLED: "true",
  XRAYLARCH_INTEGRATION_ISSUER: "playwright-drxas",
  XRAYLARCH_INTEGRATION_AUDIENCE: "playwright-athena",
  XRAYLARCH_INTEGRATION_HMAC_SECRET: "playwright-only-integration-secret-32-bytes",
  XRAYLARCH_GIT_REVISION: "0123456789abcdef0123456789abcdef01234567",
  OPENBLAS_NUM_THREADS: "1",
  OMP_NUM_THREADS: "1",
  MKL_NUM_THREADS: "1",
  VECLIB_MAXIMUM_THREADS: "1",
  XRAYLARCH_XRF_WORKERS: "1",
}

// The version badge reads these before falling back to git, so both trees render
// the same label and the badge needs no mask.
const frontendEnv = {
  BACKEND_URL: `http://127.0.0.1:${backendPort}`,
  NEXT_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
  APP_BUILD_DATE: "2026-01-01T00:00:00Z",
  APP_BUILD_COUNT: "1",
  APP_BUILD_SHA: "0000000000000000000000000000000000000000",
  NEXT_TELEMETRY_DISABLED: "1",
}

// Production builds: no dev overlay, no hot reload. The build directories reuse names
// tsconfig.json already lists, because `next build` adds any new one to it.
const standaloneBuild = ".next-verify"
const mountedBuild = ".next-cif-removal-e2e-mounted"
const serve = (port: string) => `npm run build && npm run start -- --hostname 127.0.0.1 --port ${port}`

// Playwright's headless shell has no WebGL, so the 3Dmol viewers and Plotly's 3D
// surface would not render. SwiftShader, Chromium's CPU implementation, gives WebGL
// without a GPU. The rest of the flags make the page's own rasterisation repeatable:
// on the GPU path, or with several raster threads, or re-rastering only the damaged
// part of a tile, some pixels (blurred dialog backdrops, form controls) change by a
// level or two from run to run, and a stale tile once showed through a plot.
const chromium = {
  ...devices["Desktop Chrome"],
  deviceScaleFactor: 1,
  locale: "en-US",
  timezoneId: "UTC",
  launchOptions: {
    args: [
      "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
      "--disable-gpu-rasterization", "--num-raster-threads=1", "--disable-partial-raster",
    ],
  },
}
const desktop = { width: 1440, height: 1000 }
const phone = { width: 390, height: 844 }

export default defineConfig({
  testDir: "./tests/e2e/screens",
  testMatch: /.*\.screens\.ts$/,
  globalTeardown: "./tests/e2e/global-teardown.ts",
  outputDir: "test-results/screens",
  snapshotPathTemplate: `${snapshotDir}/{projectName}/{arg}{ext}`,
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  timeout: 300_000,
  expect: {
    timeout: 20_000,
    toHaveScreenshot: {
      threshold: 0, maxDiffPixels: 0, animations: "disabled", caret: "hide", scale: "css",
      stylePath: path.join(frontendRoot, "tests/e2e/screens/volatile-fields.css"),
    },
  },
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  // The four standalone projects run the workbench specs; the mounted build runs them
  // too, under its base path, plus the Dr.XAS launch it alone serves.
  projects: [
    ...([["desktop", desktop], ["phone", phone]] as const).flatMap(([size, viewport]) => (["light", "dark"] as const).map(colorScheme => ({
      name: `${size}-${colorScheme}`,
      testIgnore: /mounted\.screens\.ts$/,
      metadata: { basePath: "", backendOrigin },
      use: { ...chromium, viewport, colorScheme, baseURL: `http://127.0.0.1:${frontendPort}` },
    }))),
    {
      name: "mounted-desktop-light",
      metadata: { basePath: appBasePath, backendOrigin },
      use: { ...chromium, viewport: desktop, colorScheme: "light" as const, baseURL: `http://127.0.0.1:${mountPort}` },
    },
  ],
  webServer: [
    {
      command: `.venv/bin/python -m uvicorn xraylarch_web.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: path.join(appRoot, "backend"),
      env: backendEnv,
      url: `http://127.0.0.1:${backendPort}/health`,
      reuseExistingServer,
    },
    {
      command: serve(frontendPort),
      cwd: appFrontend,
      env: { ...frontendEnv, NEXT_BUILD_DIR: standaloneBuild },
      url: `http://127.0.0.1:${frontendPort}`,
      timeout: 600_000,
      reuseExistingServer,
    },
    {
      command: serve(mountPort),
      cwd: appFrontend,
      env: { ...frontendEnv, NEXT_BUILD_DIR: mountedBuild, NEXT_PUBLIC_APP_BASE_PATH: appBasePath },
      url: `http://127.0.0.1:${mountPort}${appBasePath}`,
      timeout: 600_000,
      reuseExistingServer,
    },
  ],
})
