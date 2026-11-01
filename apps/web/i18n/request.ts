// next-intl's per-request config, without i18n routing: the URL never carries the language.

import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, decideLocale } from "./locale";
import { CATALOGS } from "./messages";

export default getRequestConfig(async () => {
  // Public Apply (FR-A3.4, NFR-USE-03) follows the browser's Accept-Language when no
  // NEXT_LOCALE cookie was chosen.
  const cookie = (await cookies()).get(LOCALE_COOKIE)?.value;
  const acceptLanguage = (await headers()).get("accept-language");
  const locale = decideLocale(cookie, acceptLanguage, true);
  return { locale, messages: CATALOGS[locale] };
});
