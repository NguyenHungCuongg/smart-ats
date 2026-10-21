// The UI language of a request (NFR-USE-03, SAD §5.7). The API decides an email's language by
// the same rule (app.emails.locale).

export const LOCALES = ["vi", "en"] as const;
export type Locale = (typeof LOCALES)[number];

/** Written by the language switch; the API reads it too, being on the same origin. */
export const LOCALE_COOKIE = "NEXT_LOCALE";

const supported = (value: string | undefined): value is Locale =>
  (LOCALES as readonly (string | undefined)[]).includes(value);

/**
 * The cookie's language when it is one we have; otherwise a public page (Public Apply) takes the
 * first of the browser's languages we have, and every other page is Vietnamese.
 */
export function decideLocale(
  cookie: string | undefined,
  acceptLanguage: string | null,
  isPublic: boolean,
): Locale {
  if (supported(cookie)) return cookie;
  if (!isPublic || !acceptLanguage) return "vi";
  const ranked = acceptLanguage
    .split(",")
    .map((part) => {
      const [tag, q] = part.trim().split(";q=");
      return { language: tag.split("-")[0].toLowerCase(), q: q === undefined ? 1 : Number(q) };
    })
    // q=0 refuses a language, and a malformed weight (NaN) counts for nothing.
    .filter((r) => r.q > 0)
    .sort((a, b) => b.q - a.q);
  return ranked.map((r) => r.language).find(supported) ?? "vi";
}
