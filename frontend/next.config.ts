import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  experimental: {
    agentFeedback: true,
  },
  // The dashboard is client-rendered and uses an external FastAPI service.
  // Static Hosting export cannot use Next.js PPR/Cache Components.
  cacheComponents: false,
  partialPrefetching: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
