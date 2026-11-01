import type { Metadata } from "next";

import { LOCALE_COOKIE, type Locale, decideLocale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { buildJobAd, buildJobPostingJsonLd, getJobAdExcerpt } from "../../jobs/share";
import { ApplyForm, type PublicJob } from "./form";

export async function fetchPublicJob(slug: string): Promise<PublicJob | null> {
  const baseUrl =
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    (typeof window === "undefined" ? "http://127.0.0.1:8000" : "");
  try {
    const res = await fetch(`${baseUrl}/api/apply/${slug}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export function getPublicApplyUrl(slug: string): string {
  const base =
    process.env.NEXT_PUBLIC_APP_URL || process.env.NEXT_PUBLIC_API_URL || "https://localhost";
  return `${base.replace(/\/api\/?$/, "")}/apply/${slug}`;
}

export async function getPageLocale(): Promise<Locale> {
  try {
    const { cookies, headers } = await import("next/headers");
    const cookieStore = await cookies();
    const headerStore = await headers();
    return decideLocale(
      cookieStore.get(LOCALE_COOKIE)?.value,
      headerStore.get("accept-language"),
      true,
    );
  } catch {
    return "vi";
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const job = await fetchPublicJob(slug);
  const locale = await getPageLocale();
  const t = CATALOGS[locale].apply;

  if (!job) {
    return {
      title: t.metaTitle,
    };
  }

  const publicUrl = getPublicApplyUrl(slug);
  const jobAd = buildJobAd(job, locale, publicUrl);
  const excerpt = getJobAdExcerpt(jobAd);

  return {
    title: `${job.title} | ${job.tenant_name}`,
    description: excerpt,
    openGraph: {
      title: job.title,
      description: excerpt,
      url: publicUrl,
      images: job.tenant_logo_url ? [{ url: job.tenant_logo_url }] : [],
    },
  };
}

export default async function PublicApplyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const job = await fetchPublicJob(slug);
  const locale = await getPageLocale();
  const publicUrl = getPublicApplyUrl(slug);

  const jsonLd = job ? buildJobPostingJsonLd(job, publicUrl, locale) : null;

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      )}
      <ApplyForm slug={slug} initialJob={job} />
    </>
  );
}
