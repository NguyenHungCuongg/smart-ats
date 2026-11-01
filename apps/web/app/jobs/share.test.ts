import { describe, expect, test } from "vitest";

import {
  buildFacebookShareUrl,
  buildJobAd,
  buildJobPostingJsonLd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatXTweet,
  getJobAdExcerpt,
} from "./share";

const mockJob = {
  title: "Senior Backend Engineer",
  level: "SENIOR" as const,
  department: "Platform",
  location: "Hà Nội",
  work_mode: "REMOTE" as const,
  status: "PUBLISHED",
  apply_deadline: "2026-12-31",
  public_slug: "senior-backend-engineer",
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
    const ad = buildJobAd(mockJob, "vi", publicUrl);
    expect(ad).toContain("Tuyển dụng: Senior Backend Engineer");
    expect(ad).toContain("Trách nhiệm chính:");
    expect(ad).toContain("- Thiết kế kiến trúc hệ thống");
    expect(ad).toContain("Kỹ năng chính:");
    expect(ad).toContain("- Python");
    expect(ad).toContain("- PostgreSQL");
    expect(ad).toContain("Địa điểm: Hà Nội");
    expect(ad).toContain("Hình thức làm việc: Từ xa (Remote)");
    expect(ad).toContain("Hạn nộp hồ sơ: 2026-12-31");
    expect(ad).toContain(`Ứng tuyển tại: ${publicUrl}`);
  });

  test("renders Job Ad template in English", () => {
    const ad = buildJobAd(mockJob, "en", publicUrl);
    expect(ad).toContain("Hiring: Senior Backend Engineer");
    expect(ad).toContain("Key responsibilities:");
    expect(ad).toContain("- Thiết kế kiến trúc hệ thống");
    expect(ad).toContain("Key skills:");
    expect(ad).toContain("- Python");
    expect(ad).toContain("Location: Hà Nội");
    expect(ad).toContain("Work mode: Remote");
    expect(ad).toContain("Application deadline: 2026-12-31");
    expect(ad).toContain(`Apply at: ${publicUrl}`);
  });

  test("omits optional sections when fields are missing", () => {
    const minimalJob = {
      title: "Intern Developer",
      status: "PUBLISHED",
    };
    const ad = buildJobAd(minimalJob, "vi");
    expect(ad).toBe("Tuyển dụng: Intern Developer");
  });
});

describe("getJobAdExcerpt", () => {
  test("returns trimmed excerpt for Open Graph description", () => {
    const ad = buildJobAd(mockJob, "vi", publicUrl);
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
});

describe("formatXTweet text length and link preservation", () => {
  test("keeps short text and link intact under 280 characters", () => {
    const shortText = "Tuyển dụng gấp: Backend Dev.";
    const tweet = formatXTweet(shortText, publicUrl);
    expect(tweet.length).toBeLessThanOrEqual(280);
    expect(tweet).toContain(publicUrl);
    expect(tweet).toContain(shortText);
  });

  test("truncates long text to fit X character limit while strictly preserving link", () => {
    const longJobAd = "Tuyển dụng: Senior Backend Engineer. ".repeat(20) + "\n\nNộp hồ sơ ngay!";
    const tweet = formatXTweet(longJobAd, publicUrl, 280);
    expect(tweet.length).toBeLessThanOrEqual(280);
    expect(tweet).toContain(publicUrl);
    expect(tweet.endsWith(publicUrl)).toBe(true);
    expect(tweet).toContain("…");
  });
});

describe("buildJobPostingJsonLd schema", () => {
  test("returns null when Job is not PUBLISHED", () => {
    expect(buildJobPostingJsonLd({ ...mockJob, status: "DRAFT" }, publicUrl)).toBeNull();
    expect(buildJobPostingJsonLd({ ...mockJob, status: "CLOSED" }, publicUrl)).toBeNull();
    expect(buildJobPostingJsonLd({ ...mockJob, status: "PAUSED" }, publicUrl)).toBeNull();
  });

  test("generates JSON-LD for REMOTE job with TELECOMMUTE and Việt Nam location requirement", () => {
    const jsonLd = buildJobPostingJsonLd({ ...mockJob, work_mode: "REMOTE" }, publicUrl);
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

  test("omits validThrough when apply_deadline is not set", () => {
    const jsonLd = buildJobPostingJsonLd({ ...mockJob, apply_deadline: null }, publicUrl);
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
    const jsonLd = buildJobPostingJsonLd(jobWithSalary, publicUrl);
    expect(jsonLd!.baseSalary).toBeUndefined();
  });
});
