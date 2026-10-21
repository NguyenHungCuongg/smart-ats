import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../i18n/locale";
import { CATALOGS } from "../i18n/messages";
import Home from "./page";

const render = (locale: Locale) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <Home />
    </NextIntlClientProvider>,
  );

test("home page shows the product name", () => {
  expect(render("vi")).toContain("Smart ATS");
});

test("home page leads to the Job list, in the chosen language", () => {
  expect(render("vi")).toContain('href="/jobs">Danh sách Job');
  expect(render("en")).toContain('href="/jobs">Jobs');
});
