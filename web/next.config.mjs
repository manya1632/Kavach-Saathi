const agentOrigin = process.env.AGENT_API_ORIGIN || "http://127.0.0.1:8000";
const configuredDevOrigins = (process.env.KAVACH_ALLOWED_DEV_ORIGINS || "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: [
    "julianne-unvoluminous-nonreliably.ngrok-free.dev",
    ...configuredDevOrigins,
  ],
  turbopack: { root: import.meta.dirname },
  async rewrites() {
    return [
      { source: "/agent-api/:path*", destination: `${agentOrigin}/:path*` },
      { source: "/mock-assets/:path*", destination: `${agentOrigin}/mock-assets/:path*` },
    ];
  },
};

export default nextConfig;
