import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import type { Locale } from "../../../i18n/locale";
import { buildJobAd, buildJobPostingJsonLd, getJobAdExcerpt } from "../../jobs/share";
import { ApplyForm } from "./form";
import { fetchPublicJob, getPublicApplyUrl } from "./public-job";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const job = await fetchPublicJob(slug);
  const t = await getTranslations("apply");
  const tJobAd = await getTranslations("jobAd");
  const locale = (await getLocale()) as Locale;

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
  const tJobAd = await getTranslations("jobAd");
  const locale = (await getLocale()) as Locale;
  const publicUrl = getPublicApplyUrl(slug);

  const jsonLd = job ? buildJobPostingJsonLd(job, publicUrl, tJobAd, locale) : null;

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
        />
      )}
      <ApplyForm slug={slug} initialJob={job} />
    </>
  );
}
