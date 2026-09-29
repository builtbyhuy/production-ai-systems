/** Extract the pinned test browser without applying archive ownership metadata.
 * Some user namespaces cannot chown the package's font archive entries. Keeping
 * current-user ownership avoids that metadata operation; browser bytes are unchanged.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createBrotliDecompress } from "node:zlib";
import { pipeline } from "node:stream/promises";
import { execFileSync } from "node:child_process";

let packageRoot = path.dirname(
  fileURLToPath(import.meta.resolve("@sparticuz/chromium")),
);
while (!fs.existsSync(path.join(packageRoot, "bin/chromium.br"))) {
  const parent = path.dirname(packageRoot);
  if (parent === packageRoot)
    throw new Error("Pinned Chromium payload not found. Run npm ci.");
  packageRoot = parent;
}
const output = path.resolve(
  process.env.PAIS_BROWSER_RUNTIME || "../../artifacts/ui/browser-runtime",
);
fs.mkdirSync(output, { recursive: true });
const binary = path.join(output, "chromium");
if (!fs.existsSync(binary) || fs.statSync(binary).size < 1_000_000) {
  await pipeline(
    fs.createReadStream(path.join(packageRoot, "bin/chromium.br")),
    createBrotliDecompress(),
    fs.createWriteStream(binary, { mode: 0o755 }),
  );
  fs.chmodSync(binary, 0o755);
}
for (const archive of ["fonts.tar.br", "swiftshader.tar.br"]) {
  const compressed = path.join(packageRoot, "bin", archive);
  const marker = path.join(output, `.${archive}.extracted`);
  if (fs.existsSync(compressed) && !fs.existsSync(marker)) {
    const tar = path.join(output, archive.replace(/\.br$/, ""));
    await pipeline(
      fs.createReadStream(compressed),
      createBrotliDecompress(),
      fs.createWriteStream(tar),
    );
    execFileSync("tar", [
      "--extract",
      "--file",
      tar,
      "--directory",
      output,
      "--no-same-owner",
      "--no-same-permissions",
    ]);
    fs.unlinkSync(tar);
    fs.writeFileSync(marker, "ok\n");
  }
}
const version = execFileSync(binary, ["--version"], {
  encoding: "utf8",
}).trim();
if (!version.startsWith("Chromium"))
  throw new Error("Extracted browser did not report a Chromium version.");
console.log(JSON.stringify({ executable: binary, version }));
