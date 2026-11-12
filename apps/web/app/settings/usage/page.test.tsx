import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { BudgetWarningAlert, UsageView } from "./view";
import type { UsageSummary } from "./usage";

const adminWarningSummary: UsageSummary = {
  month: "2026-04",
  scope: "TENANT",
  budget_usd: 100,
  total_cost_usd: 82.5,
  total_calls: 120,
  usage_ratio: 0.825,
  budget_warning: true,
  features: [
    { feature: "SCORING", calls: 50, cost_usd: 52.5 },
    { feature: "CV_PARSE", calls: 70, cost_usd: 30 },
  ],
};

const recruiterSummary: UsageSummary = {
  month: "2026-04",
  scope: "USER",
  budget_usd: 100,
  total_cost_usd: 12.25,
  total_calls: 15,
  usage_ratio: 0.1225,
  budget_warning: false,
  features: [],
};

const render = (
  locale: Locale,
  props: { data: UsageSummary | null; loading?: boolean; error?: string | null },
) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <UsageView
        month="2026-04"
        onMonthChange={() => {}}
        data={props.data}
        loading={props.loading ?? false}
        error={props.error ?? null}
      />
    </NextIntlClientProvider>,
  );

test("renders 80% warning banner and feature table for Company Admin", () => {
  const html = render("en", { data: adminWarningSummary });
  expect(html).toContain("Monthly AI budget warning");
  expect(html).toContain("Workspace total (Company Admin)");
  expect(html).toContain("Candidate scoring");
  expect(html).toContain("SCORING");
  expect(html).toContain("CV parsing");

  const viHtml = render("vi", { data: adminWarningSummary });
  expect(viHtml).toContain("Cảnh báo ngân sách AI hàng tháng");
  expect(viHtml).toContain("Toàn bộ Workspace (Company Admin)");
  expect(viHtml).toContain("Chấm điểm ứng viên");
});

test("hides warning banner and shows Recruiter scope and empty state when no calls", () => {
  const html = render("en", { data: recruiterSummary });
  expect(html).not.toContain("Monthly AI budget warning");
  expect(html).toContain("Your AI usage (Recruiter)");
  expect(html).toContain("No AI usage recorded for this month.");
});

test("renders error state cleanly", () => {
  const html = render("en", {
    data: null,
    error: "Only Company Admins and Recruiters can view AI usage.",
  });
  expect(html).toContain("Only Company Admins and Recruiters can view AI usage.");
});

test("BudgetWarningAlert includes link to usage details when detailsHref is provided", () => {
  const html = renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={CATALOGS.en}>
      <BudgetWarningAlert summary={adminWarningSummary} detailsHref="/settings/usage" />
    </NextIntlClientProvider>,
  );
  expect(html).toContain("Monthly AI budget warning");
  expect(html).toContain("/settings/usage");
  expect(html).toContain("View AI usage");
});
