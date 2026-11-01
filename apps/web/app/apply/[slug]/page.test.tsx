import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { ApplyForm, type PublicJob } from "./form";
import PublicApplyPage, { generateMetadata } from "./page";

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
