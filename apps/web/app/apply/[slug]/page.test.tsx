import { NextIntlClientProvider, createTranslator } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { ApplyForm, type PublicJob } from "./form";
import PublicApplyPage, { generateMetadata } from "./page";
import { fetchPublicJob, getPublicApplyUrl } from "./public-job";

let currentLocale: Locale = "en";

vi.mock("next-intl/server", () => ({
  getLocale: vi.fn(async () => currentLocale),
  getTranslations: vi.fn(async (namespace: string) => {
    return createTranslator({
      locale: currentLocale,
      messages: CATALOGS[currentLocale],
      namespace: namespace as keyof (typeof CATALOGS)[typeof currentLocale],
    });
  }),
}));

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

describe("PublicApplyPage server rendering and metadata", () => {
  const publishedJob: PublicJob = {
    job_id: "job-123",
    title: "DevOps Engineer",
    status: "PUBLISHED",
    public_apply_enabled: true,
    published_at: "2026-11-01T10:00:00Z",
    apply_deadline: "2026-12-31",
    location: "Hà Nội",
    work_mode: "REMOTE",
    criteria: {
      skills: [{ name: "Kubernetes", must_have: true }],
      responsibilities: ["Manage clusters"],
    },
    tenant_name: "Tech Corp",
    tenant_logo_url: "https://example.com/logo.png",
    tenant_privacy_notice_url: null,
    is_closed: false,
  };

  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    currentLocale = "en";
  });

  test("renders JobPosting JSON-LD when Job is PUBLISHED", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => publishedJob,
    });

    const page = await PublicApplyPage({
      params: Promise.resolve({ slug: "devops-engineer" }),
    });

    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={CATALOGS.en}>
        {page}
      </NextIntlClientProvider>,
    );

    expect(html).toContain('<script type="application/ld+json">');
    expect(html).toContain('"@type":"JobPosting"');
    expect(html).toContain('"jobLocationType":"TELECOMMUTE"');
    expect(html).toContain('"title":"DevOps Engineer"');
    expect(html).not.toContain("baseSalary");
  });

  test("escapes script tags to prevent XSS in JSON-LD", async () => {
    const xssJob: PublicJob = {
      ...publishedJob,
      title: 'DevOps Engineer </script><script>alert("xss")</script>',
      criteria: {
        skills: [{ name: "Kubernetes", must_have: true }],
        responsibilities: ['Exploit </script><script>alert("xss")</script>'],
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => xssJob,
    });

    const page = await PublicApplyPage({
      params: Promise.resolve({ slug: "devops-engineer" }),
    });

    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={CATALOGS.en}>
        {page}
      </NextIntlClientProvider>,
    );

    // Verify <script> tag closure is safely escaped as \u003c/script
    expect(html).toContain("\\u003c/script");
    expect(html).not.toContain('</script><script>alert("xss")</script>');
  });

  test("does not render JSON-LD when Job is not PUBLISHED", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...publishedJob, status: "CLOSED", is_closed: true }),
    });

    const page = await PublicApplyPage({
      params: Promise.resolve({ slug: "devops-engineer" }),
    });

    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={CATALOGS.en}>
        {page}
      </NextIntlClientProvider>,
    );

    expect(html).not.toContain('<script type="application/ld+json">');
  });

  test("generateMetadata generates Open Graph tags from Job Ad and tenant logo", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => publishedJob,
    });

    const meta = await generateMetadata({
      params: Promise.resolve({ slug: "devops-engineer" }),
    });

    expect(meta.title).toBe("DevOps Engineer | Tech Corp");
    expect(meta.description).toContain("DevOps Engineer");
    expect(meta.openGraph?.title).toBe("DevOps Engineer");
    expect(meta.openGraph?.description).toBe(meta.description);
    expect(meta.openGraph?.images).toEqual([{ url: "https://example.com/logo.png" }]);
  });
});

describe("public-job helpers", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test("getPublicApplyUrl builds URL from slug and base URL", () => {
    const url = getPublicApplyUrl("senior-dev");
    expect(url).toContain("/apply/senior-dev");
  });

  test("fetchPublicJob catches fetch errors, logs to console.error, and returns null", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    global.fetch = vi.fn().mockRejectedValue(new Error("Network failed"));

    const res = await fetchPublicJob("failed-slug");
    expect(res).toBeNull();
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
