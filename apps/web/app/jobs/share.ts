import type { Locale } from "../../i18n/locale";
import type { Translator } from "../../i18n/messages";

export type JobAdCriteria = {
  skills?: { name: string; must_have?: boolean }[] | null;
  responsibilities?: string[] | null;
};

export type JobAdInput = {
  title: string;
  location?: string | null;
  work_mode?: string | null;
  apply_deadline?: string | null;
  criteria?: JobAdCriteria | null;
};

export type JobPostingInput = JobAdInput & {
  status: string;
  public_apply_enabled?: boolean | null;
  published_at?: string | null;
  tenant_name?: string | null;
  tenant_logo_url?: string | null;
};

/**
 * Formats an apply deadline string according to locale (e.g. DD/MM/YYYY for vi, MM/DD/YYYY for en).
 */
export function formatDeadline(deadline: string, locale: Locale): string {
  const parts = deadline.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (parts) {
    const year = Number.parseInt(parts[1], 10);
    const month = Number.parseInt(parts[2], 10) - 1;
    const day = Number.parseInt(parts[3], 10);
    return new Date(year, month, day).toLocaleDateString(locale);
  }
  const d = new Date(deadline);
  if (!Number.isNaN(d.getTime())) {
    return d.toLocaleDateString(locale);
  }
  return deadline;
}

/**
 * Builds a Job Ad from Job details in the chosen locale (FR-A3.5, SAD §5.6).
 * Pure function of Job, translator, locale and public URL.
 */
export function buildJobAd(
  job: JobAdInput,
  t: Translator<"jobAd">,
  locale: Locale,
  publicUrl?: string,
): string {
  const sections: string[] = [];

  // Title
  sections.push(t("title", { title: job.title }));

  // Responsibilities
  if (job.criteria?.responsibilities && job.criteria.responsibilities.length > 0) {
    const items = job.criteria.responsibilities.map((r) => `- ${r}`).join("\n");
    sections.push(`${t("responsibilities")}\n${items}`);
  }

  // Key skills (prioritizing must_have if present)
  if (job.criteria?.skills && job.criteria.skills.length > 0) {
    const mustHave = job.criteria.skills.filter((s) => s.must_have);
    const keySkills = mustHave.length > 0 ? mustHave : job.criteria.skills;
    const items = keySkills.map((s) => `- ${s.name}`).join("\n");
    sections.push(`${t("skills")}\n${items}`);
  }

  // Metadata: location, work mode, deadline
  const meta: string[] = [];
  if (job.location) {
    meta.push(t("location", { location: job.location }));
  }
  if (job.work_mode) {
    const modeKey = job.work_mode as "REMOTE" | "HYBRID" | "ONSITE";
    const modeLabel =
      modeKey === "REMOTE" || modeKey === "HYBRID" || modeKey === "ONSITE"
        ? t(`workModes.${modeKey}`)
        : job.work_mode;
    meta.push(t("workMode", { mode: modeLabel }));
  }
  if (job.apply_deadline) {
    const deadlineFormatted = formatDeadline(job.apply_deadline, locale);
    meta.push(t("deadline", { deadline: deadlineFormatted }));
  }
  if (meta.length > 0) {
    sections.push(meta.join("\n"));
  }

  // Apply Link
  if (publicUrl) {
    sections.push(t("applyLink", { url: publicUrl }));
  }

  return sections.join("\n\n");
}

/**
 * Extracts a short summary/excerpt from a Job Ad for Open Graph description.
 */
export function getJobAdExcerpt(jobAd: string, maxLength = 200): string {
  if (jobAd.length <= maxLength) return jobAd;
  const trimmed = jobAd.slice(0, maxLength - 1);
  const lastSpace = trimmed.lastIndexOf(" ");
  const clean = lastSpace > 0 ? trimmed.slice(0, lastSpace) : trimmed;
  return `${clean}…`;
}

/**
 * Generates LinkedIn share-offsite URL with the Public Apply link.
 */
export function buildLinkedInShareUrl(publicUrl: string): string {
  return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(publicUrl)}`;
}

/**
 * Generates Facebook dialog/share URL with app id and Public Apply link.
 */
export function buildFacebookShareUrl(appId: string, publicUrl: string): string {
  return `https://www.facebook.com/dialog/share?app_id=${encodeURIComponent(appId)}&href=${encodeURIComponent(publicUrl)}`;
}

/**
 * Trọng số theo twitter-text v3: URL = 23; code point ngoài các khoảng dưới đây = 2.
 */
export function xWeight(text: string): number {
  let n = 0;
  for (const ch of text) {
    const c = ch.codePointAt(0) ?? 0;
    const light =
      c <= 0x10ff ||
      (c >= 0x2000 && c <= 0x200d) ||
      (c >= 0x2010 && c <= 0x201f) ||
      (c >= 0x2032 && c <= 0x2037);
    n += light ? 1 : 2;
  }
  return n;
}

/** Truncates a string so that its xWeight does not exceed maxW. */
function truncateToXWeight(str: string, maxW: number): string {
  let w = 0;
  let acc = "";
  for (const ch of str) {
    const charWeight = xWeight(ch);
    if (w + charWeight > maxW) break;
    w += charWeight;
    acc += ch;
  }
  return acc.trim();
}

/**
 * Formats a tweet for X within character weights (default 280), strictly preserving the link.
 */
export function formatXTweet(text: string, publicUrl: string, maxWeight = 280): string {
  if (text.includes(publicUrl)) {
    const nonUrl = text.replace(publicUrl, "");
    if (xWeight(nonUrl) + 23 <= maxWeight) return text;

    const beforeUrl = text.slice(0, text.indexOf(publicUrl)).trim();
    const availableWeight = maxWeight - 23 - xWeight("…\n");
    if (availableWeight <= 0) return publicUrl;
    const truncated = truncateToXWeight(beforeUrl, availableWeight);
    return `${truncated}…\n${publicUrl}`;
  }

  // Need to append publicUrl
  if (xWeight(text) + 1 + 23 <= maxWeight) {
    return `${text} ${publicUrl}`;
  }
  const availableWeight = maxWeight - 23 - xWeight("… ");
  if (availableWeight <= 0) return publicUrl;
  const truncated = truncateToXWeight(text, availableWeight);
  return `${truncated}… ${publicUrl}`;
}

/**
 * Generates X intent/tweet URL with text and Public Apply link.
 * Avoids duplicating the link if it is already embedded in the text.
 */
export function buildXShareUrl(text: string, publicUrl?: string): string {
  if (!publicUrl || text.includes(publicUrl)) {
    return `https://x.com/intent/tweet?text=${encodeURIComponent(text)}`;
  }
  return `https://x.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(publicUrl)}`;
}

/**
 * Builds schema.org JobPosting structured data (FR-A3.5).
 * Returns null if Job is not PUBLISHED, public apply is disabled, published_at is missing,
 * or location is missing for a non-remote job.
 */
export function buildJobPostingJsonLd(
  job: JobPostingInput,
  publicUrl: string,
  t: Translator<"jobAd">,
  locale: Locale,
): Record<string, unknown> | null {
  if (job.status !== "PUBLISHED" || !job.public_apply_enabled || !job.published_at) {
    return null;
  }

  let jobLocation: Record<string, unknown> | undefined;
  let jobLocationType: string | undefined;
  let applicantLocationRequirements: Record<string, unknown> | undefined;

  if (job.work_mode === "REMOTE") {
    jobLocationType = "TELECOMMUTE";
    applicantLocationRequirements = {
      "@type": "Country",
      name: "Việt Nam",
    };
  } else if (job.location) {
    jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: job.location,
        addressCountry: "VN",
      },
    };
  } else {
    // Non-remote job without location cannot produce valid JobPosting
    return null;
  }

  const description = buildJobAd(job, t, locale, publicUrl);

  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description,
    datePosted: job.published_at,
    hiringOrganization: {
      "@type": "Organization",
      name: job.tenant_name || "",
      ...(job.tenant_logo_url ? { logo: job.tenant_logo_url } : {}),
    },
  };

  if (jobLocationType) {
    jsonLd.jobLocationType = jobLocationType;
  }
  if (applicantLocationRequirements) {
    jsonLd.applicantLocationRequirements = applicantLocationRequirements;
  }
  if (jobLocation) {
    jsonLd.jobLocation = jobLocation;
  }

  if (job.apply_deadline) {
    jsonLd.validThrough = job.apply_deadline;
  }

  return jsonLd;
}
