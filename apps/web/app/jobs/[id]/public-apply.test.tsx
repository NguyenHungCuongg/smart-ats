import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { Job } from "../criteria";
import { PublicApplySection } from "./public-apply";

const dummyJob: Job = {
  id: "job-1",
  title: "Backend Engineer",
  level: "MID",
  department: null,
  location: null,
  work_mode: null,
  status: "PUBLISHED",
  parse_status: "SUCCEEDED",
  parse_error: null,
  criteria: null,
  verification: null,
  weights: { technical: 50, soft_skills: 25, experience: 25 },
  criteria_confirmed_at: null,
  apply_deadline: null,
  public_apply_enabled: false,
  public_slug: null,
};

const render = (locale: Locale, job: Job) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <PublicApplySection job={job} onSaved={() => {}} />
    </NextIntlClientProvider>,
  );

test("public apply section shows disabled status and enable action when disabled", () => {
  const html = render("en", dummyJob);
  expect(html).toContain("Public Apply Link");
  expect(html).toContain("Disabled");
  expect(html).toContain("Enable");
});

test("public apply section shows enabled status and disable action when enabled", () => {
  const html = render("en", {
    ...dummyJob,
    public_apply_enabled: true,
    public_slug: "test-slug-123",
  });
  expect(html).toContain("Enabled");
  expect(html).toContain("Disable");
  expect(html).toContain("Copy link");
});

test("in Vietnamese too", () => {
  const html = render("vi", dummyJob);
  expect(html).toContain("Public Apply Link");
  expect(html).toContain("Đang tắt");
  expect(html).toContain("Bật");
});
