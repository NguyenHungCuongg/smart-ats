import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { Job } from "../criteria";
import { JobAdSection } from "./share";

const dummyJob: Job = {
  id: "job-1",
  title: "Senior Backend Engineer",
  level: "SENIOR",
  department: "Tech",
  location: "Hà Nội",
  work_mode: "REMOTE",
  status: "PUBLISHED",
  parse_status: "SUCCEEDED",
  parse_error: null,
  criteria: {
    skills: [{ name: "Python", must_have: true }],
    min_years_experience: 5,
    education: null,
    responsibilities: ["Develop APIs"],
    salary_range: null,
  },
  verification: null,
  weights: { technical: 50, soft_skills: 25, experience: 25 },
  criteria_confirmed_at: "2026-11-01T10:00:00Z",
  apply_deadline: "2026-12-31",
  public_apply_enabled: true,
  public_slug: "test-slug-123",
};

const render = (locale: Locale, job: Job, facebookAppId?: string) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <JobAdSection job={job} facebookAppId={facebookAppId} />
    </NextIntlClientProvider>,
  );

describe("JobAdSection component", () => {
  test("shows editable textarea and active buttons when Job is PUBLISHED and public link enabled", () => {
    const html = render("en", dummyJob);
    expect(html).toContain("Share Job Ad");
    expect(html).toContain("Copy Ad");
    expect(html).toContain("Share to LinkedIn");
    expect(html).toContain("Share to X");
    expect(html).toContain("Hiring: Senior Backend Engineer");
    // Not disabled
    expect(html).not.toContain('disabled=""');
  });

  test("hides Facebook share button when app id is not configured", () => {
    const html = render("en", dummyJob, "");
    expect(html).not.toContain("Share to Facebook");
  });

  test("shows Facebook share button when app id is configured", () => {
    const html = render("en", dummyJob, "fb-12345");
    expect(html).toContain("Share to Facebook");
  });

  test("disables controls and shows reason when Job is not PUBLISHED", () => {
    const html = render("en", { ...dummyJob, status: "DRAFT" });
    expect(html).toContain('disabled=""');
    expect(html).toContain("Job must be in Published status to share.");
  });

  test("disables controls and shows reason when public link is off", () => {
    const html = render("en", { ...dummyJob, public_apply_enabled: false });
    expect(html).toContain('disabled=""');
    expect(html).toContain("Public Apply Link is disabled. Enable it to share.");
  });

  test("renders in Vietnamese", () => {
    const html = render("vi", dummyJob);
    expect(html).toContain("Đăng tin");
    expect(html).toContain("Chép tin");
    expect(html).toContain("Chia sẻ LinkedIn");
    expect(html).toContain("Chia sẻ X");
    expect(html).toContain("Tuyển dụng: Senior Backend Engineer");
  });
});
