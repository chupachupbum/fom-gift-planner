/**
 * web/planner.worker.js
 *
 * Dedicated Web Worker running Pyodide 0.26.4 WASM runtime for Fields of Mistria Gift Planner.
 * Processes .sav save files 100% client-side with zero server communication.
 */

// Pyodide CDN configuration
const PYODIDE_CDN_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const WHEEL_FILENAME = "fom_gift_planner-1.2.0-py3-none-any.whl";
const DATA_FILES = [
  "item_data.json",
  "recipes.json",
  "alt_sources.json",
  "item_locations.json",
  "recipe_sources.json",
  "item_seasons.json"
];

let pyodide = null;
let isReady = false;
let initPromise = null;
let lastSavePath = "/tmp/upload.sav";
let lastFilename = "upload.sav";

/**
 * Initializes Pyodide runtime, micropip, wheel, VFS data databases, and web bridge.
 */
async function handleInit() {
  if (isReady && pyodide) {
    self.postMessage({ action: "ready" });
    return;
  }

  if (initPromise) {
    await initPromise;
    self.postMessage({ action: "ready" });
    return;
  }

  initPromise = (async () => {
    // Step 1: Pyodide loading
    self.postMessage({
      action: "progress",
      step: "pyodide",
      percent: 20,
      message: "Loading Pyodide WASM runtime..."
    });

    if (typeof loadPyodide === "undefined") {
      importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");
    }

    pyodide = await loadPyodide({
      indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
    });

    // Step 2: micropip package loading
    self.postMessage({
      action: "progress",
      step: "micropip",
      percent: 40,
      message: "Loading micropip package manager..."
    });

    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");

    // Step 3: Install local wheel
    self.postMessage({
      action: "progress",
      step: "wheel",
      percent: 60,
      message: "Installing Fields of Mistria gift planner wheel..."
    });

    const wheelUrl = new URL(WHEEL_FILENAME, self.location.href).href;
    await micropip.install(wheelUrl);

    // Step 4: Populate data databases into Pyodide VFS
    self.postMessage({
      action: "progress",
      step: "data",
      percent: 80,
      message: "Populating game databases into virtual filesystem..."
    });

    pyodide.FS.mkdirTree("/data");
    await Promise.all(
      DATA_FILES.map(async (fileName) => {
        const url = new URL("data/" + fileName, self.location.href).href;
        const resp = await fetch(url);
        if (!resp.ok) {
          throw new Error(`Failed to fetch data/${fileName}: HTTP ${resp.status}`);
        }
        const text = await resp.text();
        pyodide.FS.writeFile("/data/" + fileName, text);
      })
    );

    // Step 5: Populate Python web bridge module
    self.postMessage({
      action: "progress",
      step: "bridge",
      percent: 95,
      message: "Initializing Python web bridge..."
    });

    pyodide.FS.mkdirTree("/home/pyodide");
    const bridgeUrl = new URL("py/web_bridge.py", self.location.href).href;
    const bridgeResp = await fetch(bridgeUrl);
    if (!bridgeResp.ok) {
      throw new Error(`Failed to fetch py/web_bridge.py: HTTP ${bridgeResp.status}`);
    }
    const bridgeCode = await bridgeResp.text();
    pyodide.FS.writeFile("/home/pyodide/web_bridge.py", bridgeCode);

    // Import web_bridge and initialize bridge with /data
    pyodide.runPython(`
import sys
if "/home/pyodide" not in sys.path:
    sys.path.insert(0, "/home/pyodide")
import web_bridge
web_bridge.init_bridge('/data')
`);

    isReady = true;
  })();

  await initPromise;
  self.postMessage({ action: "ready" });
}

/**
 * Handles plan generation on a new save file.
 */
async function handlePlan(data) {
  if (!isReady || !pyodide) {
    await handleInit();
  }

  if (!data.saveBytes) {
    throw new Error("Missing required saveBytes in plan request.");
  }

  const startTime = performance.now();
  pyodide.FS.mkdirTree("/tmp");

  const filename = data.filename || "upload.sav";
  const savePath = "/tmp/" + filename;
  const saveBytes = data.saveBytes instanceof Uint8Array
    ? data.saveBytes
    : new Uint8Array(data.saveBytes);

  pyodide.FS.writeFile(savePath, saveBytes);
  if (savePath !== "/tmp/upload.sav") {
    pyodide.FS.writeFile("/tmp/upload.sav", saveBytes);
  }

  lastSavePath = savePath;
  lastFilename = filename;

  const webBridge = pyodide.pyimport("web_bridge");
  const configDict = data.config
    ? (typeof data.config === "string" ? data.config : JSON.stringify(data.config))
    : "{}";

  const resultJson = webBridge.generate_plan(savePath, configDict, filename);
  const plan = JSON.parse(resultJson);
  const durationMs = Math.round(performance.now() - startTime);

  self.postMessage({
    action: "result",
    plan: plan,
    data: plan,
    durationMs: durationMs
  });
}

/**
 * Handles recomputing plan on existing save file in VFS with updated config.
 */
async function handleRecompute(data) {
  if (!isReady || !pyodide) {
    await handleInit();
  }

  const savePath = "/tmp/upload.sav";
  let exists = false;
  try {
    exists = pyodide.FS.analyzePath(savePath).exists;
  } catch (e) {
    exists = false;
  }

  if (!exists) {
    throw new Error("No save file available in VFS (/tmp/upload.sav) to recompute. Please upload a save file first.");
  }

  const startTime = performance.now();
  const filename = lastFilename || "upload.sav";
  const webBridge = pyodide.pyimport("web_bridge");
  const configDict = data.config
    ? (typeof data.config === "string" ? data.config : JSON.stringify(data.config))
    : "{}";

  const resultJson = webBridge.generate_plan(savePath, configDict, filename);
  const plan = JSON.parse(resultJson);
  const durationMs = Math.round(performance.now() - startTime);

  self.postMessage({
    action: "result",
    plan: plan,
    data: plan,
    durationMs: durationMs
  });
}

/**
 * Global message handler implementing complete message protocol.
 */
self.onmessage = async function (event) {
  const data = event.data || {};
  const action = data.action;

  try {
    switch (action) {
      case "init":
        await handleInit();
        break;
      case "plan":
        await handlePlan(data);
        break;
      case "recompute":
        await handleRecompute(data);
        break;
      default:
        throw new Error(`Unknown action: ${action}`);
    }
  } catch (err) {
    self.postMessage({
      action: "error",
      message: err.message || String(err),
      detail: err.stack || "",
      error: err.message || String(err),
      stack: err.stack || ""
    });
  }
};
