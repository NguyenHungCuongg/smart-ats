"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { LOCALES, LOCALE_COOKIE, type Locale } from "../i18n/locale";

// Each in its own language, so a reader finds theirs whichever is shown.
const NAMES: Record<Locale, string> = { vi: "Tiếng Việt", en: "English" };
const YEAR = 60 * 60 * 24 * 365;

/** Remembered on this device; the API reads the same cookie to pick an email's language. */
function remember(locale: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${YEAR}; samesite=lax`;
}

/** Switches the UI language in place: remembered on the device, the URL and page state kept. */
export function LocaleSwitch() {
  const t = useTranslations("locale");
  const current = useLocale();
  const router = useRouter();

  function choose(locale: Locale) {
    remember(locale);
    // Server components render again in the new language; client state stays.
    router.refresh();
  }

  return (
    <div role="group" aria-label={t("label")} className="flex gap-4">
      {LOCALES.map((locale) => (
        <button
          key={locale}
          type="button"
          lang={locale}
          aria-pressed={locale === current}
          onClick={() => choose(locale)}
          // button-cap-light type; as in link-on-light, the underline marks the one to press.
          className={`py-2 text-sm/[1.29] tracking-[0.2px] uppercase ${
            locale === current ? "font-bold" : "font-medium underline"
          }`}
        >
          {NAMES[locale]}
        </button>
      ))}
    </div>
  );
}
