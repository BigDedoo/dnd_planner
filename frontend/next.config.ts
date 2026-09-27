import type { NextConfig } from "next";
import path from "node:path";

const apiUpstreamUrl = (
  process.env.API_UPSTREAM_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  // The public Terms page shares its versioned document with the backend.
  turbopack: { root: path.resolve(__dirname, "..") },
  // Clerk's supported SDK opt-out, applied to client and Next server bundles.
  // This is non-secret policy configuration, in development and production builds.
  env: { NEXT_PUBLIC_CLERK_TELEMETRY_DISABLED: "1" },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUpstreamUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
