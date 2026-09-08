/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: false },
  async rewrites() {
    // In Docker the browser talks to localhost:8000 directly (CORS is enabled),
    // but server components / SSR can proxy through the internal address.
    const internal = process.env.API_INTERNAL_BASE_URL;
    return internal
      ? [{ source: "/proxy/:path*", destination: `${internal}/:path*` }]
      : [];
  },
};
export default nextConfig;
