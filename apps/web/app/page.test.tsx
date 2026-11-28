import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../i18n/locale";
import { CATALOGS } from "../i18n/messages";
import type { DashboardSummary } from "./dashboard";
import { DashboardView, type DashboardViewProps } from "./page";
import type { UsageSummary } from "./settings/usage/usage";

const SAMPLE_USAGE: UsageSummary = {
  month: "2026-11",
  scope: "TENANT",
  budget_usd: 100,
  total_cost_usd: 42.5,
  total_calls: 85,
  usage_ratio: 0.425,
  budget_warning: false,
  features: [],
};

const POPULATED_SUMMARY: DashboardSummary = {
  total_jobs: 4,
  jobs_by_status: {
    DRAFT: 1,
    PUBLISHED: 2,
    PAUSED: 0,
    CLOSED: 1,
    ARCHIVED: 0,
  },
  total_applications: 10,
  pipeline_by_stage: {
    APPLIED: 4,
    SCREENING: 2,
    SHORTLISTED: 1,
    INTERVIEW: 1,
    OFFER: 1,
    HIRED: 1,
    REJECTED: 0,
  },
  action_items: {
    pending_criteria_jobs: {
      count: 1,
      items: [
        {
          id: "job-criteria-1",
          title: "Backend Python Engineer",
          level: "SENIOR",
          status: "DRAFT",
          application_count: 0,
        },
      ],
    },
    failed_parse_jobs: {
      count: 1,
      items: [
        {
          id: "job-failed-1",
          title: "Data Platform Lead",
          level: "LEAD",
          status: "DRAFT",
          application_count: 0,
        },
      ],
    },
    unscored_jobs: {
      count: 1,
      items: [
        {
          id: "job-unscored-1",
          title: "Product Designer",
          level: "MID",
          status: "PUBLISHED",
          application_count: 3,
        },
      ],
    },
    new_applications_count: 4,
  },
  recent_jobs: [
    {
      id: "job-unscored-1",
      title: "Product Designer",
      level: "MID",
      department: "Design",
      location: "HCM",
      status: "PUBLISHED",
      parse_status: "SUCCEEDED",
      criteria_confirmed: true,
      application_count: 3,
      created_at: "2026-11-25T09:00:00Z",
    },
  ],
  recent_activity: [
    {
      id: "act-1",
      action: "job.created",
      actor_type: "USER",
      actor: { id: "u-1", full_name: "Nguyễn Văn An" },
      before: null,
      after: { status: "DRAFT" },
      created_at: "2026-11-25T09:05:00Z",
    },
    {
      id: "act-2",
      action: "application.scored",
      actor_type: "SYSTEM",
      actor: null,
      before: { status: "PENDING" },
      after: { scoring_run_id: "r-1", status: "SCORED", total_score: 86.4 },
      created_at: "2026-11-25T09:10:00Z",
    },
  ],
};

const EMPTY_SUMMARY: DashboardSummary = {
  total_jobs: 0,
  jobs_by_status: {
    DRAFT: 0,
    PUBLISHED: 0,
    PAUSED: 0,
    CLOSED: 0,
    ARCHIVED: 0,
  },
  total_applications: 0,
  pipeline_by_stage: {
    APPLIED: 0,
    SCREENING: 0,
    SHORTLISTED: 0,
    INTERVIEW: 0,
    OFFER: 0,
    HIRED: 0,
    REJECTED: 0,
  },
  action_items: {
    pending_criteria_jobs: { count: 0, items: [] },
    failed_parse_jobs: { count: 0, items: [] },
    unscored_jobs: { count: 0, items: [] },
    new_applications_count: 0,
  },
  recent_jobs: [],
  recent_activity: [],
};

function renderDashboard(locale: Locale, props: Partial<DashboardViewProps> = {}) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <DashboardView
        role="COMPANY_ADMIN"
        data={POPULATED_SUMMARY}
        usage={SAMPLE_USAGE}
        loading={false}
        error={false}
        {...props}
      />
    </NextIntlClientProvider>,
  );
}

function countOccurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

test("renders populated console Dashboard in Vietnamese and English with single CTA and button-inverted", () => {
  const viHtml = renderDashboard("vi");
  expect(viHtml).toContain("Tổng quan Workspace");
  expect(viHtml).toContain("Job đang tuyển");
  expect(viHtml).toContain("Phễu Pipeline toàn Workspace");
  expect(viHtml).toContain("Cần xử lý");
  expect(viHtml).toContain('href="/jobs/job-failed-1"');
  expect(viHtml).toContain('href="/jobs/job-criteria-1"');
  expect(viHtml).toContain('href="/jobs/job-unscored-1"');
  expect(viHtml).toContain("Nguyễn Văn An đã tạo Job.");
  expect(viHtml).toContain("Hệ thống đã chấm điểm Application (Total 86,4).");
  // Single primary CTA to /jobs/new on populated screen
  expect(countOccurrences(viHtml, 'href="/jobs/new"')).toBe(1);
  // Featured Dark Card uses button-inverted with explicit text-ink-deep invariance
  expect(viHtml).toMatch(/class="[^"]*button-inverted[^"]*text-ink-deep[^"]*"/);
  expect(viHtml).toContain('href="/settings/usage"');

  const enHtml = renderDashboard("en");
  expect(enHtml).toContain("Workspace Overview");
  expect(enHtml).toContain("Published Jobs");
  expect(enHtml).toContain("Workspace Pipeline");
  expect(enHtml).toContain("Action Queue");
  expect(enHtml).toContain("Nguyễn Văn An created the Job.");
  expect(enHtml).toContain("System scored the Application (Total 86.4).");
  expect(countOccurrences(enHtml, 'href="/jobs/new"')).toBe(1);
});

test("renders Empty Onboarding in vi and en with direct action verbs and a single Create Job CTA", () => {
  const viHtml = renderDashboard("vi", { data: EMPTY_SUMMARY, role: "RECRUITER" });
  expect(viHtml).toContain("Khởi tạo quy trình tuyển dụng đầu tiên");
  expect(viHtml).toContain("Tải JD lên");
  expect(viHtml).toContain("Thêm hồ sơ ứng viên");
  expect(viHtml).toContain("Chấm điểm AI");
  expect(viHtml).not.toMatch(/Bước\s*\d/i);
  expect(countOccurrences(viHtml, 'href="/jobs/new"')).toBe(1);

  const enHtml = renderDashboard("en", { data: EMPTY_SUMMARY, role: "RECRUITER" });
  expect(enHtml).toContain("Start your first hiring workflow");
  expect(enHtml).toContain("Upload a JD");
  expect(enHtml).toContain("Add candidate CVs");
  expect(enHtml).toContain("Run AI scoring");
  expect(enHtml).not.toMatch(/Step\s*\d/i);
  expect(countOccurrences(enHtml, 'href="/jobs/new"')).toBe(1);
});

test("renders REVIEWER Dashboard without Create Job CTA, AI spend card, or management actions", () => {
  const reviewerSummary: DashboardSummary = {
    ...POPULATED_SUMMARY,
    total_jobs: 1,
    action_items: {
      pending_criteria_jobs: { count: 0, items: [] },
      failed_parse_jobs: { count: 0, items: [] },
      unscored_jobs: { count: 0, items: [] },
      new_applications_count: 2,
    },
  };

  const viHtml = renderDashboard("vi", {
    role: "REVIEWER",
    data: reviewerSummary,
    usage: null,
  });
  expect(viHtml).toContain("Job được phân công");
  expect(viHtml).toContain('href="/jobs"');
  expect(viHtml).not.toContain('href="/jobs/new"');
  expect(viHtml).not.toContain('href="/settings/usage"');
  expect(viHtml).not.toContain("Chi phí AI tháng hiện tại");

  const emptyReviewerEn = renderDashboard("en", {
    role: "REVIEWER",
    data: EMPTY_SUMMARY,
    usage: null,
  });
  expect(emptyReviewerEn).toContain("No assigned Jobs yet");
  expect(emptyReviewerEn).not.toContain('href="/jobs/new"');
});

test("renders skeleton loading and localized API error states in vi and en", () => {
  const loadingVi = renderDashboard("vi", { data: null, loading: true });
  expect(loadingVi).toContain('aria-busy="true"');
  expect(loadingVi).not.toContain('href="/jobs/new"');

  const errorVi = renderDashboard("vi", {
    data: null,
    loading: false,
    error: true,
    onRetry: () => {},
  });
  expect(errorVi).toContain('role="alert"');
  expect(errorVi).toContain("Không tải được dữ liệu tổng quan. Kiểm tra kết nối rồi thử lại.");
  expect(errorVi).toContain("Thử lại");

  const errorEn = renderDashboard("en", {
    data: null,
    loading: false,
    error: true,
    onRetry: () => {},
  });
  expect(errorEn).toContain(
    "Could not load the overview data. Check your connection and try again.",
  );
  expect(errorEn).toContain("Retry");
});

test("enforces anti-AI-slop rules: at most 1 uppercase eyebrow, no 01 / numbering, zero em/en-dashes in new catalogs", () => {
  const html = renderDashboard("en");
  // No 01 / or 02 / section numbering
  expect(html).not.toMatch(/\b0[1-9]\s*\//);

  // At most 1 uppercase tracking-[0.2px] eyebrow paragraph on the Dashboard
  const eyebrowMatches = html.match(/<p[^>]*tracking-\[0\.2px\][^>]*uppercase/g) ?? [];
  expect(eyebrowMatches.length).toBeLessThanOrEqual(1);

  // Zero em-dashes (—) or en-dashes (–) in nav and dashboard catalog strings
  const newStrings = JSON.stringify({
    viNav: CATALOGS.vi.nav,
    viDashboard: CATALOGS.vi.dashboard,
    enNav: CATALOGS.en.nav,
    enDashboard: CATALOGS.en.dashboard,
  });
  expect(newStrings).not.toContain("—");
  expect(newStrings).not.toContain("–");
});
