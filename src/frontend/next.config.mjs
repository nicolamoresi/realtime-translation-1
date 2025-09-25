/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Se avevi opzioni 'experimental', 'images', 'webpack', 'rewrites', copiale qui sotto.
  // Esempio:
  // experimental: { esmExternals: 'loose' },
  // images: { domains: ['example.com'] },
  // async rewrites() {
  //   return [{ source: '/healthz', destination: '/api/health' }];
  // },
};

// Se nel TS c'erano export default nextConfig;
export default nextConfig;
// Se preferisci CommonJS con next.config.js, usa invece: module.exports = nextConfig;
