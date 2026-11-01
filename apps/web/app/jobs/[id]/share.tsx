"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { Locale } from "../../../i18n/locale";
import type { Job } from "../criteria";
import {
  buildFacebookShareUrl,
  buildJobAd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatXTweet,
} from "../share";

function subscribe() {
  return () => {};
}

function getOriginSnapshot() {
  return window.location.origin;
}

function getServerOriginSnapshot() {
  return "";
}

export function JobAdSection({
  job,
  facebookAppId,
  publicUrl: customPublicUrl,
}: {
  job: Job;
  facebookAppId?: string;
  publicUrl?: string;
}) {
  const t = useTranslations("jobShare");
  const locale = useLocale() as Locale;
  const [copied, setCopied] = useState(false);
  const origin = useSyncExternalStore(subscribe, getOriginSnapshot, getServerOriginSnapshot);

  const publicUrl =
    customPublicUrl ??
    (job.public_slug
      ? origin
        ? `${origin}/apply/${job.public_slug}`
        : `/apply/${job.public_slug}`
      : "");

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
        aria-label={t("adContent")}
        disabled={!isReady}
        onChange={(e) => setEditedContent(e.target.value)}
        className="w-full rounded-sm border border-hairline-cool bg-surface-canvas-light p-3 text-sm text-ink-deep focus:inset-shadow-input focus:outline-none focus-visible:ring-2 focus-visible:ring-ring-focus disabled:opacity-50"
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!isReady}
          onClick={copyToClipboard}
          className="button-outline text-sm whitespace-nowrap"
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
