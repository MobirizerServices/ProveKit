/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone", // slim container image; ignored by `next dev`
};
module.exports = nextConfig;
