/** @type {import('next').NextConfig} */
const internal = process.env.API_INTERNAL_BASE_URL?.replace(/\/$/, "");

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: false },
  async rewrites() {
    if (!internal) return [];
    // Same-origin proxy: when the client bundle is built with an empty
    // NEXT_PUBLIC_API_BASE_URL (single-service deploys, e.g. Render), the browser
    // calls "/api/*" and Next forwards it to the API service. Avoids CORS and
    // build-time API-URL baking. `/proxy/*` is kept for SSR/server components.
    return [
      { source: "/api/:path*", destination: `${internal}/api/:path*` },
      { source: "/proxy/:path*", destination: `${internal}/:path*` },
    ];
  },
};
export default nextConfig;
