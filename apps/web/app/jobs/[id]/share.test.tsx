import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { Translator } from "../../../i18n/messages";
import type { Job } from "../criteria";
import { type FacebookJobChannelStatus, JobAdSection, getPublishErrorMessage } from "./share";

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

const render = (
  locale: Locale,
  job: Job,
  facebookAppId?: string,
  initialChannelStatus?: FacebookJobChannelStatus,
) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <JobAdSection
        job={job}
        facebookAppId={facebookAppId}
        initialChannelStatus={initialChannelStatus}
      />
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

  test("shows notice when Facebook Page is not connected", () => {
    const html = render("en", dummyJob, undefined, {
      connected: false,
      posts: [],
    });
    expect(html).toContain("Facebook Page");
    expect(html).toContain(
      "Facebook Page is not connected. A Company Admin needs to connect a Page in Settings.",
    );
  });

  test("shows connected page name and active publish button when connected", () => {
    const html = render("en", dummyJob, undefined, {
      connected: true,
      page_name: "Tech Corp Official",
      page_id: "page-123",
      posts: [],
    });
    expect(html).toContain("Page: Tech Corp Official");
    expect(html).toContain("Publish to Facebook Page");
  });

  test("renders list of published channel posts", () => {
    const html = render("en", dummyJob, undefined, {
      connected: true,
      page_name: "Tech Corp Official",
      page_id: "page-123",
      posts: [
        {
          id: "post-1",
          job_id: "job-1",
          channel: "FACEBOOK_PAGE",
          target_id: "page-123",
          external_post_id: "fb-post-456",
          url: "https://www.facebook.com/fb-post-456",
          body: "Job Ad body",
          posted_by: "user-1",
          posted_by_name: "Alice Recruiter",
          posted_at: "2026-11-20T10:00:00Z",
        },
      ],
    });
    expect(html).toContain("Published Posts");
    expect(html).toContain("Facebook Page");
    expect(html).toContain("Alice Recruiter");
    expect(html).toContain("https://www.facebook.com/fb-post-456");
    expect(html).toContain("View Post");
  });

  test("renders Facebook Page section in Vietnamese", () => {
    const html = render("vi", dummyJob, undefined, {
      connected: true,
      page_name: "Công ty Công nghệ",
      page_id: "page-123",
      posts: [
        {
          id: "post-1",
          job_id: "job-1",
          channel: "FACEBOOK_PAGE",
          target_id: "page-123",
          external_post_id: "fb-post-456",
          url: "https://www.facebook.com/fb-post-456",
          body: "Job Ad body",
          posted_by: "user-1",
          posted_by_name: "Nguyễn Văn A",
          posted_at: "2026-11-20T10:00:00Z",
        },
      ],
    });
    expect(html).toContain("Trang: Công ty Công nghệ");
    expect(html).toContain("Đăng lên Facebook Page");
    expect(html).toContain("Bài viết đã đăng");
    expect(html).toContain("Nguyễn Văn A");
    expect(html).toContain("Xem bài viết");
  });

  test("maps error codes to localized strings", () => {
    const tEn = ((key: string) =>
      (CATALOGS.en.jobShare as Record<string, string>)[key] ??
      key) as unknown as Translator<"jobShare">;
    const tVi = ((key: string) =>
      (CATALOGS.vi.jobShare as Record<string, string>)[key] ??
      key) as unknown as Translator<"jobShare">;

    expect(getPublishErrorMessage(tEn, "TOKEN_EXPIRED")).toContain(
      "Facebook Page session has expired",
    );
    expect(getPublishErrorMessage(tVi, "TOKEN_EXPIRED")).toContain(
      "Phiên đăng nhập Facebook Page đã hết hạn",
    );

    expect(getPublishErrorMessage(tEn, "NOT_CONNECTED")).toContain(
      "Facebook Page is not connected",
    );
    expect(getPublishErrorMessage(tVi, "NOT_CONNECTED")).toContain("Chưa kết nối Facebook Page");

    expect(getPublishErrorMessage(tEn, "TIMEOUT")).toContain("Facebook request timed out");
    expect(getPublishErrorMessage(tVi, "TIMEOUT")).toContain(
      "Hết thời gian chờ phản hồi từ Facebook",
    );

    expect(getPublishErrorMessage(tEn, "UNKNOWN")).toContain("Failed to publish to Facebook Page");
    expect(getPublishErrorMessage(tEn, null)).toBeNull();
  });
});
