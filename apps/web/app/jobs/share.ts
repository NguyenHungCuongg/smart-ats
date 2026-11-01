import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";

export type JobAdCriteria = {
  skills?: { name: string; must_have?: boolean }[] | null;
  responsibilities?: string[] | null;
};

export type JobAdInput = {
  title: string;
  location?: string | null;
  work_mode?: string | null;
  apply_deadline?: string | null;
  status?: string | null;
  public_slug?: string | null;
  criteria?: JobAdCriteria | null;
};

export type JobPostingInput = {
  title: string;
  status: string;
  work_mode?: string | null;
  location?: string | null;
  apply_deadline?: string | null;
  published_at?: string | null;
  tenant_name?: string | null;
  tenant_logo_url?: string | null;
  criteria?: JobAdCriteria | null;
};

/**
 * Builds a Job Ad from Job details in the chosen locale (FR-A3.5, SAD §5.6).
 * Pure function of Job and locale.
 */
export function buildJobAd(job: JobAdInput, locale: Locale = "vi", publicUrl?: string): string {
  const t = CATALOGS[locale].jobAd;
  const sections: string[] = [];

  // Title
  sections.push(t.title.replace("{title}", job.title));

  // Responsibilities
  if (job.criteria?.responsibilities && job.criteria.responsibilities.length > 0) {
    const items = job.criteria.responsibilities.map((r) => `- ${r}`).join("\n");
    sections.push(`${t.responsibilities}\n${items}`);
  }

  // Key skills (prioritizing must_have if present)
  if (job.criteria?.skills && job.criteria.skills.length > 0) {
    const mustHave = job.criteria.skills.filter((s) => s.must_have);
    const keySkills = mustHave.length > 0 ? mustHave : job.criteria.skills;
    const items = keySkills.map((s) => `- ${s.name}`).join("\n");
    sections.push(`${t.skills}\n${items}`);
  }

  // Metadata: location, work mode, deadline
  const meta: string[] = [];
  if (job.location) {
    meta.push(t.location.replace("{location}", job.location));
  }
  if (job.work_mode) {
    const modeKey = job.work_mode as keyof typeof t.workModes;
    const modeLabel = t.workModes[modeKey] ?? job.work_mode;
    meta.push(t.workMode.replace("{mode}", modeLabel));
  }
  if (job.apply_deadline) {
    meta.push(t.deadline.replace("{deadline}", job.apply_deadline));
  }
  if (meta.length > 0) {
    sections.push(meta.join("\n"));
  }

  // Apply Link
  if (publicUrl) {
    sections.push(t.applyLink.replace("{url}", publicUrl));
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
 * Formats a tweet for X within character limits (default 280), strictly preserving the link.
 */
export function formatXTweet(text: string, publicUrl: string, maxLen = 280): string {
  if (text.includes(publicUrl)) {
    if (text.length <= maxLen) return text;
    // Truncate non-url part
    const beforeUrl = text.slice(0, text.indexOf(publicUrl)).trim();
    const availableForText = maxLen - publicUrl.length - 2; // for newline and ellipsis
    if (availableForText <= 0) return publicUrl;
    const truncated = beforeUrl.slice(0, availableForText).trim();
    return `${truncated}…\n${publicUrl}`;
  }

  // Need to append publicUrl
  const reserve = publicUrl.length + 2; // space + ellipsis
  if (text.length + publicUrl.length + 1 <= maxLen) {
    return `${text} ${publicUrl}`;
  }
  const availableForText = maxLen - reserve;
  if (availableForText <= 0) return publicUrl;
  const truncated = text.slice(0, availableForText).trim();
  return `${truncated}… ${publicUrl}`;
}

/**
 * Generates X intent/tweet URL with text and Public Apply link.
 */
export function buildXShareUrl(text: string, publicUrl: string): string {
  return `https://x.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(publicUrl)}`;
}

/**
 * Builds schema.org JobPosting structured data (FR-A3.5).
 * Returns null if Job is not in PUBLISHED status.
 */
export function buildJobPostingJsonLd(
  job: JobPostingInput,
  publicUrl: string,
  locale: Locale = "vi",
): Record<string, unknown> | null {
  if (job.status !== "PUBLISHED") {
    return null;
  }

  const description = buildJobAd(job, locale, publicUrl);

  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description,
    datePosted: job.published_at ?? new Date().toISOString(),
    hiringOrganization: {
      "@type": "Organization",
      name: job.tenant_name || "",
      ...(job.tenant_logo_url ? { logo: job.tenant_logo_url } : {}),
    },
  };

  if (job.work_mode === "REMOTE") {
    jsonLd.jobLocationType = "TELECOMMUTE";
    jsonLd.applicantLocationRequirements = {
      "@type": "Country",
      name: "Việt Nam",
    };
  } else if (job.work_mode === "HYBRID" || job.work_mode === "ONSITE") {
    jsonLd.jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: job.location || "Việt Nam",
        addressCountry: "VN",
      },
    };
  }

  if (job.apply_deadline) {
    jsonLd.validThrough = job.apply_deadline;
  }

  return jsonLd;
}
