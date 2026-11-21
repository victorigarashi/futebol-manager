// Shared launcher: system Chrome with the GPU enabled when available (falls back to SwiftShader).
const BASE = process.env.LAB_URL || "http://127.0.0.1:5190";
async function launch(chromium, opts = {}) {
  return chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/google-chrome",
    headless: process.env.HEADED ? false : true,
    args: ["--no-sandbox", "--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=" + (process.env.ANGLE || "gl"), "--enable-features=Vulkan", ...(opts.args || [])],
  });
}
module.exports = { launch, BASE };
