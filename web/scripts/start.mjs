import { cp } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const standalone = join(root, ".next", "standalone");
await cp(join(root, ".next", "static"), join(standalone, ".next", "static"), {
  recursive: true,
});

const child = spawn(process.execPath, [join(standalone, "server.js")], {
  cwd: standalone,
  stdio: "inherit",
  env: {
    ...process.env,
    HOSTNAME: process.env.RESEARCH_WEB_HOST || "127.0.0.1",
    PORT: process.env.PORT || "3000",
  },
});
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code || 0;
});
