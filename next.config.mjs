/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingIncludes: {
    "/api/inflation/*": ["./data/inflation/*.json"],
  },
};
export default nextConfig;
