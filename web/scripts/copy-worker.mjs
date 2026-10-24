// Copies the pinned MapLibre worker into /public so the UI is fully self-hosted (no CDN).
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(root, "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs");
const dst = join(root, "public", "maplibre-gl-worker.mjs");
mkdirSync(dirname(dst), { recursive: true });
copyFileSync(src, dst);
console.log(`copied ${src} -> ${dst}`);
