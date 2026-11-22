/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  typescript: { ignoreBuildErrors: false },
  env: { REACT_APP_BACKEND_URL: process.env.REACT_APP_BACKEND_URL || "" },
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      // Keep Next inline scripts/styles, external images and private blob previews usable.
      { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'" },
    ];
    if (process.env.NODE_ENV === "production") {
      securityHeaders.push({ key: "Strict-Transport-Security", value: "max-age=31536000" });
    }
    return [
      { source: "/:path*", headers: securityHeaders },
      ...["/forgot-password", "/reset-password", "/change-password", "/pricing"].map((source) => ({
        source,
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cache-Control", value: "no-store" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      })),
    ];
  },
  async rewrites() {
    if (process.env.NODE_ENV === "production" && !(
      process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || process.env.REACT_APP_BACKEND_URL
    )) {
      throw new Error("An explicit backend origin is required in production.");
    }
    const backend = new URL(
      process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL ||
      process.env.REACT_APP_BACKEND_URL || "http://127.0.0.1:8001",
    );
    if (!["http:", "https:"].includes(backend.protocol) || backend.username || backend.password ||
        backend.pathname !== "/" || backend.search || backend.hash) {
      throw new Error("Backend URL must be an HTTP(S) origin without a path, credentials, query, or fragment.");
    }
    return [{ source: "/api/:path*", destination: `${backend.origin}/api/:path*` }];
  },
};

module.exports = nextConfig;
