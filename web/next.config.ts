import type { NextConfig } from "next";

// Static export: the FastAPI service serves `out/` locally and on Modal; `next dev`
// talks to the API through NEXT_PUBLIC_API_BASE (see .env.development).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: false,
  images: { unoptimized: true },
  turbopack: {
    root: __dirname,
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
