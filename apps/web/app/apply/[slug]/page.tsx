import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { getTranslations } from "next-intl/server";

import { LOCALE_COOKIE, type Locale, decideLocale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { buildJobAd, buildJobPostingJsonLd, getJobAdExcerpt } from "../../jobs/share";
import { ApplyForm } from "./form";
import { fetchPublicJob, getPublicApplyUrl } from "./public-job";

// A public page: without the cookie it follows the browser's language, unlike the rest of the
// app (i18n/request.ts), so metadata, JSON-LD and the form all use this one.
async function publicLocale(): Promise<Locale> {
  const cookie = (await cookies()).get(LOCALE_COOKIE)?.value;
  return decideLocale(cookie, (await headers()).get("accept-language"), true);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const job = await fetchPublicJob(slug);
  const locale = await publicLocale();
  const t = await getTranslations({ locale, namespace: "apply" });
  const tJobAd = await getTranslations({ locale, namespace: "jobAd" });

  if (!job) {
    return {
      title: t("metaTitle"),
    };
  }

  const publicUrl = getPublicApplyUrl(slug);
  const jobAd = buildJobAd(job, tJobAd, locale, publicUrl);
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
  const locale = await publicLocale();
  const tJobAd = await getTranslations({ locale, namespace: "jobAd" });
  const publicUrl = getPublicApplyUrl(slug);

  const jsonLd = job ? buildJobPostingJsonLd(job, publicUrl, tJobAd, locale) : null;

  return (
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
        />
      )}
      <ApplyForm slug={slug} initialJob={job} />
    </NextIntlClientProvider>
  );
}
