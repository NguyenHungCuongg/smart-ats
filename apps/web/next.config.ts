import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const nextConfig: NextConfig = {};

// Points next-intl at i18n/request.ts.
export default createNextIntlPlugin()(nextConfig);
