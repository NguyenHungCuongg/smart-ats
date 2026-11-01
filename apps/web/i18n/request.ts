// next-intl's per-request config, without i18n routing: the URL never carries the language.

import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, decideLocale } from "./locale";
import { CATALOGS } from "./messages";

export default getRequestConfig(async () => {
  // Every page but Public Apply ignores Accept-Language and defaults to vi; Public Apply
  // (FR-A3.4) decides its own language in app/apply/[slug]/page.tsx.
  const locale = decideLocale((await cookies()).get(LOCALE_COOKIE)?.value, null, false);
  return { locale, messages: CATALOGS[locale] };
});
