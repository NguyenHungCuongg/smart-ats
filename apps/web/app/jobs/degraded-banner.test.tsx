import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { DegradedAlert } from "./degraded-banner";

const render = (locale: Locale, degraded: boolean) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <DegradedAlert degraded={degraded} />
    </NextIntlClientProvider>,
  );

test("renders nothing when AI is healthy", () => {
  expect(render("en", false)).toBe("");
  expect(render("vi", false)).toBe("");
});

test("renders degraded alert in English and Vietnamese when degraded", () => {
  const enHtml = render("en", true);
  expect(enHtml).toContain('role="alert"');
  expect(enHtml).toContain("AI processing is temporarily paused");

  const viHtml = render("vi", true);
  expect(viHtml).toContain('role="alert"');
  expect(viHtml).toContain("Xử lý AI đang tạm hoãn");
});
