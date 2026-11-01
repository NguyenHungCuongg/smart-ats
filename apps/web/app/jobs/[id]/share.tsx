"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import type { Locale } from "../../../i18n/locale";
import type { Job } from "../criteria";
import {
  buildFacebookShareUrl,
  buildJobAd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatXTweet,
} from "../share";
import { clientPublicApplyUrl, useCopied } from "./clipboard";

export function JobAdSection({ job, facebookAppId }: { job: Job; facebookAppId?: string }) {
  const t = useTranslations("jobShare");
  const tJobAd = useTranslations("jobAd");
  const locale = useLocale() as Locale;
  const { copied, copy } = useCopied();

  const publicUrl = clientPublicApplyUrl(job.public_slug);

  const defaultContent = buildJobAd(job, tJobAd, locale, publicUrl);
  const [editedContent, setEditedContent] = useState<string | null>(null);
  const content = editedContent ?? defaultContent;

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
        className="w-full text-input"
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!isReady}
          onClick={() => copy(content)}
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
