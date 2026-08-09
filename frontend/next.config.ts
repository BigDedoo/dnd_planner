import type { NextConfig } from "next";

const apiUpstreamUrl = (
  process.env.API_UPSTREAM_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
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
