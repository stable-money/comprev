import type { NextConfig } from "next";

// Proxy /api/* to the FastAPI backend so the browser stays same-origin (no CORS).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Self-contained server bundle for a small production Docker image.
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
