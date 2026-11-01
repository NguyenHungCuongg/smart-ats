import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_FACEBOOK_APP_ID:
      process.env.NEXT_PUBLIC_FACEBOOK_APP_ID ?? process.env.FACEBOOK_APP_ID ?? "",
  },
};

// Points next-intl at i18n/request.ts.
export default createNextIntlPlugin()(nextConfig);
