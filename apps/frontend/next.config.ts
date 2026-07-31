import type { NextConfig } from "next";
import { publicRouteHeaders } from "./public-route-headers.mjs";

const nextConfig: NextConfig = {
  headers: publicRouteHeaders,
};

export default nextConfig;
