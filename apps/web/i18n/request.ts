// next-intl's per-request config, without i18n routing: the URL never carries the language.

import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, decideLocale } from "./locale";
import { CATALOGS } from "./messages";

export default getRequestConfig(async () => {
  // ponytail: no page is public yet (login and accept invitation default to vi like the rest),
  // so Accept-Language never counts; Public Apply (FR-A3.4) passes
  // headers().get("accept-language") and true once it exists.
  const locale = decideLocale((await cookies()).get(LOCALE_COOKIE)?.value, null, false);
  return { locale, messages: CATALOGS[locale] };
});
