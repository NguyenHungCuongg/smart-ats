"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { Locale } from "../../../i18n/locale";
import type { Job } from "../criteria";
import {
  buildFacebookShareUrl,
  buildJobAd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatXTweet,
} from "../share";

export function JobAdSection({ job, facebookAppId }: { job: Job; facebookAppId?: string }) {
  const t = useTranslations("jobShare");
  const locale = useLocale() as Locale;
  const [copied, setCopied] = useState(false);

  const publicUrl =
    typeof window !== "undefined" && job.public_slug
      ? `${window.location.origin}/apply/${job.public_slug}`
      : job.public_slug
        ? `/apply/${job.public_slug}`
        : "";

  const defaultContent = buildJobAd(job, locale, publicUrl);
  const [editedContent, setEditedContent] = useState<string | null>(null);
  const content = editedContent ?? defaultContent;

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => setCopied(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [copied]);

  const isPublished = job.status === "PUBLISHED";
  const isLinkEnabled = job.public_apply_enabled;
  const isReady = isPublished && isLinkEnabled;

  const disabledReason = !isPublished
    ? t("disabledNotPublished")
    : !isLinkEnabled
      ? t("disabledPublicApplyOff")
      : null;

  const appId =
    facebookAppId !== undefined ? facebookAppId : process.env.NEXT_PUBLIC_FACEBOOK_APP_ID;

  async function copyToClipboard() {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      // Ignore clipboard write failures
    }
  }

  function shareLinkedIn() {
    if (!publicUrl) return;
    window.open(buildLinkedInShareUrl(publicUrl), "_blank", "noopener,noreferrer");
  }

  function shareFacebook() {
    if (!publicUrl || !appId) return;
    window.open(buildFacebookShareUrl(appId, publicUrl), "_blank", "noopener,noreferrer");
  }

  function shareX() {
    if (!publicUrl) return;
    const tweetText = formatXTweet(content, publicUrl);
    window.open(buildXShareUrl(tweetText, publicUrl), "_blank", "noopener,noreferrer");
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-hairline-cloud bg-surface-night/10 p-4 dark:border-hairline-violet">
      <div className="flex flex-col gap-1">
        <span className="font-semibold">{t("title")}</span>
        <p className="text-sm opacity-80">{t("description")}</p>
      </div>

      {disabledReason && <p className="text-xs text-accent-pink">{disabledReason}</p>}

      <textarea
        rows={8}
        value={content}
        disabled={!isReady}
        onChange={(e) => setEditedContent(e.target.value)}
        className="focus:border-ink w-full rounded-md border border-hairline-cloud bg-transparent p-3 text-sm focus:outline-none disabled:opacity-50 dark:border-hairline-violet dark:focus:border-on-primary"
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!isReady}
          onClick={copyToClipboard}
          className="button-primary text-sm whitespace-nowrap"
        >
          {copied ? t("copied") : t("copyAd")}
        </button>

        <button
          type="button"
          disabled={!isReady}
          onClick={shareLinkedIn}
          className="button-outline text-sm whitespace-nowrap"
        >
          {t("shareLinkedIn")}
        </button>

        {Boolean(appId) && (
          <button
            type="button"
            disabled={!isReady}
            onClick={shareFacebook}
            className="button-outline text-sm whitespace-nowrap"
          >
            {t("shareFacebook")}
          </button>
        )}

        <button
          type="button"
          disabled={!isReady}
          onClick={shareX}
          className="button-outline text-sm whitespace-nowrap"
        >
          {t("shareX")}
        </button>
      </div>
    </div>
  );
}
