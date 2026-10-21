import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { ApplyForm } from "./form";

const render = (locale: Locale) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <ApplyForm slug="test-job-slug" />
    </NextIntlClientProvider>,
  );

test("public apply form initial render shows loading skeleton with aria-busy", () => {
  const html = render("en");
  expect(html).toContain('aria-busy="true"');
});

test("in Vietnamese too", () => {
  const html = render("vi");
  expect(html).toContain('aria-busy="true"');
});
