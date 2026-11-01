import { createTranslator } from "next-intl";
import { describe, expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import {
  buildFacebookShareUrl,
  buildJobAd,
  buildJobPostingJsonLd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatDeadline,
  formatXTweet,
  getJobAdExcerpt,
  xWeight,
} from "./share";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "jobAd" });

const mockJob = {
  title: "Senior Backend Engineer",
  level: "SENIOR" as const,
  department: "Platform",
  location: "Hà Nội",
  work_mode: "REMOTE" as const,
  status: "PUBLISHED",
  public_apply_enabled: true,
  apply_deadline: "2026-12-31",
  criteria: {
    skills: [
      { name: "Python", must_have: true },
      { name: "PostgreSQL", must_have: true },
      { name: "Docker", must_have: false },
    ],
    responsibilities: ["Thiết kế kiến trúc hệ thống", "Tối ưu hiệu năng cơ sở dữ liệu"],
  },
  tenant_name: "Acme Corp",
  tenant_logo_url: "https://example.com/logo.png",
  published_at: "2026-11-01T10:00:00Z",
};

const publicUrl = "https://ats.example.com/apply/senior-backend-engineer";

describe("buildJobAd template", () => {
  test("renders Job Ad template in Vietnamese", () => {
    const ad = buildJobAd(mockJob, t("vi"), "vi", publicUrl);
    expect(ad).toContain("Tuyển dụng: Senior Backend Engineer");
    expect(ad).toContain("Trách nhiệm chính:");
    expect(ad).toContain("- Thiết kế kiến trúc hệ thống");
    expect(ad).toContain("Kỹ năng chính:");
    expect(ad).toContain("- Python");
    expect(ad).toContain("- PostgreSQL");
    expect(ad).toContain("Địa điểm: Hà Nội");
    expect(ad).toContain("Hình thức làm việc: Từ xa (Remote)");
    expect(ad).toContain(`Hạn nộp hồ sơ: ${formatDeadline(mockJob.apply_deadline, "vi")}`);
    expect(ad).toContain(`Ứng tuyển tại: ${publicUrl}`);
  });

  test("renders Job Ad template in English", () => {
    const ad = buildJobAd(mockJob, t("en"), "en", publicUrl);
    expect(ad).toContain("Hiring: Senior Backend Engineer");
    expect(ad).toContain("Key responsibilities:");
    expect(ad).toContain("- Thiết kế kiến trúc hệ thống");
    expect(ad).toContain("Key skills:");
    expect(ad).toContain("- Python");
    expect(ad).toContain("Location: Hà Nội");
    expect(ad).toContain("Work mode: Remote");
    expect(ad).toContain(`Application deadline: ${formatDeadline(mockJob.apply_deadline, "en")}`);
    expect(ad).toContain(`Apply at: ${publicUrl}`);
  });

  test("handles special characters in title properly with ICU arguments", () => {
    const jobWithAmpersand = {
      ...mockJob,
      title: "C++ & Python Developer (Senior & Lead)",
    };
    const ad = buildJobAd(jobWithAmpersand, t("vi"), "vi");
    expect(ad).toContain("Tuyển dụng: C++ & Python Developer (Senior & Lead)");
  });

  test("omits optional sections when fields are missing", () => {
    const minimalJob = {
      title: "Intern Developer",
    };
    const ad = buildJobAd(minimalJob, t("vi"), "vi");
    expect(ad).toBe("Tuyển dụng: Intern Developer");
  });
});

describe("getJobAdExcerpt", () => {
  test("returns trimmed excerpt for Open Graph description", () => {
    const ad = buildJobAd(mockJob, t("vi"), "vi", publicUrl);
    const excerpt = getJobAdExcerpt(ad, 100);
    expect(excerpt.length).toBeLessThanOrEqual(100);
    expect(excerpt).toContain("Tuyển dụng: Senior Backend Engineer");
  });
});

describe("share intent URLs and encoding", () => {
  test("buildLinkedInShareUrl encodes the public link correctly", () => {
    const url = "https://ats.example.com/apply/job-slug?ref=linkedin&tag=tech";
    const shareUrl = buildLinkedInShareUrl(url);
    expect(shareUrl).toBe(
      `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
    );
  });

  test("buildFacebookShareUrl encodes app_id and href", () => {
    const appId = "1234567890";
    const url = "https://ats.example.com/apply/job-slug";
    const shareUrl = buildFacebookShareUrl(appId, url);
    expect(shareUrl).toBe(
      `https://www.facebook.com/dialog/share?app_id=${encodeURIComponent(appId)}&href=${encodeURIComponent(url)}`,
    );
  });

  test("buildXShareUrl encodes tweet text and link", () => {
    const text = "Tuyển dụng: Kỹ sư phần mềm (Lương hấp dẫn & Cơ hội lớn)";
    const url = "https://ats.example.com/apply/job-slug";
    const shareUrl = buildXShareUrl(text, url);
    expect(shareUrl).toBe(
      `https://x.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
    );
  });

  test("buildXShareUrl does not duplicate url when text already includes it", () => {
    const url = "https://ats.example.com/apply/job-slug";
    const text = `Tuyển dụng: Kỹ sư phần mềm\n${url}`;
    const shareUrl = buildXShareUrl(text, url);
    expect(shareUrl).toBe(`https://x.com/intent/tweet?text=${encodeURIComponent(text)}`);
    expect(shareUrl).not.toContain("&url=");
  });
});

describe("formatDeadline helper", () => {
  test("formats ISO YYYY-MM-DD date by locale", () => {
    const formattedVi = formatDeadline("2026-12-31", "vi");
    const formattedEn = formatDeadline("2026-12-31", "en");
    expect(formattedVi).toBeTruthy();
    expect(formattedEn).toBeTruthy();
  });

  test("falls back cleanly on invalid date string", () => {
    expect(formatDeadline("invalid-date", "vi")).toBe("invalid-date");
  });
});

describe("formatXTweet and xWeight calculation", () => {
  test("xWeight weights Vietnamese diacritics and ellipses as 2", () => {
    // Basic ascii
    expect(xWeight("abc")).toBe(3);
    // Vietnamese characters with combining diacritics in U+1EA0..U+1EF9 range count 2
    expect(xWeight("ế")).toBe(2);
    expect(xWeight("ệ")).toBe(2);
    expect(xWeight("ạ")).toBe(2);
    expect(xWeight("ữ")).toBe(2);
    // Ellipsis … (U+2026) counts 2
    expect(xWeight("…")).toBe(2);
  });

  test("keeps short text and link intact under 280 weight", () => {
    const shortText = "Tuyển dụng gấp: Backend Dev.";
    const tweet = formatXTweet(shortText, publicUrl);
    const nonUrl = tweet.replace(publicUrl, "");
    expect(xWeight(nonUrl) + 23).toBeLessThanOrEqual(280);
    expect(tweet).toContain(publicUrl);
    expect(tweet).toContain(shortText);
  });

  test("truncates heavily accented Vietnamese text strictly within 280 X-weight", () => {
    // Heavily accented Vietnamese string
    const heavilyAccentedText =
      "Tuyển dụng kỹ sư phần mềm cao cấp, chế độ đãi ngộ vượt trội, môi trường chuyên nghiệp, " +
      "cơ hội thăng tiến rộng mở, mức lương cạnh tranh, thưởng dự án hấp dẫn, bảo hiểm sức khỏe toàn diện. ".repeat(
        3,
      );
    const tweet = formatXTweet(heavilyAccentedText, publicUrl, 280);

    // Calculate total X weight: non-url weight + 23 for URL
    expect(tweet).toContain(publicUrl);
    const nonUrl = tweet.replace(publicUrl, "");
    const totalWeight = xWeight(nonUrl) + 23;
    expect(totalWeight).toBeLessThanOrEqual(280);
    expect(tweet).toContain("…");
  });

  test("truncates when publicUrl is already inside text", () => {
    const heavilyAccentedText =
      `Tuyển dụng: Kỹ sư lập trình cao cấp tại Hà Nội với mức đãi ngộ đặc biệt hấp dẫn. `.repeat(
        5,
      ) + `\n${publicUrl}`;
    const tweet = formatXTweet(heavilyAccentedText, publicUrl, 280);

    expect(tweet).toContain(publicUrl);
    const nonUrl = tweet.replace(publicUrl, "");
    const totalWeight = xWeight(nonUrl) + 23;
    expect(totalWeight).toBeLessThanOrEqual(280);
  });
});

describe("buildJobPostingJsonLd schema", () => {
  test("returns null when Job is not PUBLISHED", () => {
    expect(
      buildJobPostingJsonLd({ ...mockJob, status: "DRAFT" }, publicUrl, t("vi"), "vi"),
    ).toBeNull();
    expect(
      buildJobPostingJsonLd({ ...mockJob, status: "CLOSED" }, publicUrl, t("vi"), "vi"),
    ).toBeNull();
    expect(
      buildJobPostingJsonLd({ ...mockJob, status: "PAUSED" }, publicUrl, t("vi"), "vi"),
    ).toBeNull();
  });

  test("returns null when public_apply_enabled is false", () => {
    expect(
      buildJobPostingJsonLd({ ...mockJob, public_apply_enabled: false }, publicUrl, t("vi"), "vi"),
    ).toBeNull();
  });

  test("returns null when published_at is missing", () => {
    expect(
      buildJobPostingJsonLd({ ...mockJob, published_at: null }, publicUrl, t("vi"), "vi"),
    ).toBeNull();
  });

  test("generates JSON-LD for REMOTE job with TELECOMMUTE and Việt Nam location requirement even without location", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, work_mode: "REMOTE", location: null },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).not.toBeNull();
    expect(jsonLd!["@context"]).toBe("https://schema.org");
    expect(jsonLd!["@type"]).toBe("JobPosting");
    expect(jsonLd!.title).toBe("Senior Backend Engineer");
    expect(jsonLd!.jobLocationType).toBe("TELECOMMUTE");
    expect(jsonLd!.applicantLocationRequirements).toEqual({
      "@type": "Country",
      name: "Việt Nam",
    });
    expect(jsonLd!.jobLocation).toBeUndefined();
    expect(jsonLd!.datePosted).toBe("2026-11-01T10:00:00Z");
    expect(jsonLd!.validThrough).toBe("2026-12-31");
    expect(jsonLd!.baseSalary).toBeUndefined();
    expect(jsonLd!.hiringOrganization).toEqual({
      "@type": "Organization",
      name: "Acme Corp",
      logo: "https://example.com/logo.png",
    });
  });

  test("generates JSON-LD for HYBRID job with jobLocation from location", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, work_mode: "HYBRID", location: "Đà Nẵng" },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).not.toBeNull();
    expect(jsonLd!.jobLocationType).toBeUndefined();
    expect(jsonLd!.jobLocation).toEqual({
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: "Đà Nẵng",
        addressCountry: "VN",
      },
    });
  });

  test("generates JSON-LD for ONSITE job with jobLocation from location", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, work_mode: "ONSITE", location: "Hồ Chí Minh" },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).not.toBeNull();
    expect(jsonLd!.jobLocation).toEqual({
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: "Hồ Chí Minh",
        addressCountry: "VN",
      },
    });
  });

  test("returns null when work_mode is null and location is null", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, work_mode: null, location: null },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).toBeNull();
  });

  test("generates jobLocation when work_mode is null but location is present", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, work_mode: null, location: "Hà Nội" },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).not.toBeNull();
    expect(jsonLd!.jobLocation).toEqual({
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: "Hà Nội",
        addressCountry: "VN",
      },
    });
  });

  test("omits validThrough when apply_deadline is not set", () => {
    const jsonLd = buildJobPostingJsonLd(
      { ...mockJob, apply_deadline: null },
      publicUrl,
      t("vi"),
      "vi",
    );
    expect(jsonLd).not.toBeNull();
    expect(jsonLd!.validThrough).toBeUndefined();
  });

  test("never outputs baseSalary", () => {
    const jobWithSalary = {
      ...mockJob,
      criteria: {
        ...mockJob.criteria,
        salary_range: "30M - 50M VND",
      },
    };
    const jsonLd = buildJobPostingJsonLd(jobWithSalary, publicUrl, t("vi"), "vi");
    expect(jsonLd!.baseSalary).toBeUndefined();
  });
});
