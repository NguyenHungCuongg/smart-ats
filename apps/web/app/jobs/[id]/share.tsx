"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { Locale } from "../../../i18n/locale";
import { apiFetch } from "../../auth";
import type { Job } from "../criteria";
import {
  buildFacebookShareUrl,
  buildJobAd,
  buildLinkedInShareUrl,
  buildXShareUrl,
  formatXTweet,
} from "../share";
import { clientPublicApplyUrl, useCopied } from "./clipboard";

export interface ChannelPost {
  id: string;
  job_id: string;
  channel: string;
  target_id: string;
  external_post_id: string;
  url: string;
  body: string;
  posted_by: string;
  posted_by_name: string;
  posted_at: string;
}

export interface FacebookJobChannelStatus {
  connected: boolean;
  page_name?: string | null;
  page_id?: string | null;
  posts: ChannelPost[];
}

export function JobAdSection({
  job,
  facebookAppId,
  initialChannelStatus,
}: {
  job: Job;
  facebookAppId?: string;
  initialChannelStatus?: FacebookJobChannelStatus;
}) {
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

  const [channelStatus, setChannelStatus] = useState<FacebookJobChannelStatus | null>(
    initialChannelStatus ?? null,
  );
  const [loadingStatus, setLoadingStatus] = useState(initialChannelStatus === undefined);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishSuccess, setPublishSuccess] = useState<string | null>(null);
  const [isAlreadyPublished, setIsAlreadyPublished] = useState(false);

  useEffect(() => {
    if (initialChannelStatus !== undefined) return;
    let active = true;
    apiFetch(`/api/jobs/${job.id}/channels/facebook`).then(async (res) => {
      if (!active) return;
      if (res.status === 401) {
        window.location.replace("/login");
        return;
      }
      if (res.ok) {
        setChannelStatus(await res.json());
      }
      setLoadingStatus(false);
    });
    return () => {
      active = false;
    };
  }, [job.id, initialChannelStatus]);

  async function publishToFacebook() {
    if (!isReady || publishing) return;
    setPublishing(true);
    setPublishError(null);
    setPublishSuccess(null);

    const res = await apiFetch(`/api/jobs/${job.id}/channel-posts/facebook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: content }),
    });

    setPublishing(false);
    if (res.status === 401) {
      window.location.replace("/login");
      return;
    }

    if (res.ok) {
      const data: ChannelPost = await res.json();
      setIsAlreadyPublished(res.status === 200);
      setPublishSuccess(data.url);
      setChannelStatus((prev) => ({
        connected: prev?.connected ?? true,
        page_name: prev?.page_name ?? null,
        page_id: prev?.page_id ?? null,
        posts: [data, ...(prev?.posts.filter((p) => p.id !== data.id) ?? [])],
      }));
      return;
    }

    const err = await res.json().catch(() => null);
    const code = err?.detail?.code ?? err?.detail;
    if (code === "TOKEN_EXPIRED") {
      setPublishError(t("errorTokenExpired"));
    } else if (code === "NOT_CONNECTED") {
      setPublishError(t("errorNotConnected"));
    } else if (code === "TIMEOUT") {
      setPublishError(t("errorTimeout"));
    } else if (code === "JOB_NOT_PUBLISHED") {
      setPublishError(t("disabledNotPublished"));
    } else if (code === "PUBLIC_APPLY_DISABLED") {
      setPublishError(t("disabledPublicApplyOff"));
    } else {
      setPublishError(t("errorFailed"));
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
    <div className="flex flex-col gap-4 rounded-lg border border-hairline-cloud bg-surface-night/10 p-4 dark:border-hairline-violet">
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

      {/* Facebook Page Channel Section */}
      <div className="flex flex-col gap-3 rounded-md border border-hairline-cloud bg-surface-night/5 p-3 dark:border-hairline-violet">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{t("facebookPage")}</span>
            {channelStatus?.connected && channelStatus.page_name && (
              <span className="rounded-full bg-accent-violet/10 px-2.5 py-0.5 text-xs font-medium text-accent-violet">
                {t("connectedPage", { name: channelStatus.page_name })}
              </span>
            )}
          </div>
        </div>

        {!loadingStatus && channelStatus && !channelStatus.connected && (
          <div className="flex flex-col gap-1 text-sm text-accent-pink">
            <p>{t("notConnected")}</p>
          </div>
        )}

        {channelStatus?.connected && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!isReady || publishing}
              onClick={publishToFacebook}
              className="button-outline text-sm font-medium whitespace-nowrap"
            >
              {publishing ? t("publishing") : t("publishFacebook")}
            </button>
          </div>
        )}

        {publishError && (
          <p role="alert" className="text-xs text-accent-pink">
            {publishError}
          </p>
        )}

        {publishSuccess && (
          <div
            role="status"
            className="rounded flex flex-col gap-1 bg-accent-violet/10 p-2 text-xs text-accent-violet"
          >
            <span>{isAlreadyPublished ? t("alreadyPublished") : t("publishedSuccess")}</span>
            <a
              href={publishSuccess}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium underline hover:opacity-80"
            >
              {t("viewPost")} →
            </a>
          </div>
        )}

        {channelStatus?.posts && channelStatus.posts.length > 0 && (
          <div className="mt-2 flex flex-col gap-2 border-t border-hairline-cloud pt-2 dark:border-hairline-violet">
            <span className="text-text-mid text-xs font-medium tracking-wider uppercase">
              {t("channelPostsTitle")}
            </span>
            <ul className="flex flex-col gap-2">
              {channelStatus.posts.map((post) => (
                <li
                  key={post.id}
                  className="rounded flex flex-wrap items-center justify-between gap-2 border border-hairline-cloud/50 bg-surface-night/10 p-2 text-xs dark:border-hairline-violet/50"
                >
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">
                        {post.channel === "FACEBOOK_PAGE" ? "Facebook Page" : post.channel}
                      </span>
                      <span className="opacity-70">
                        {t("postedBy", {
                          name: post.posted_by_name,
                          time: new Date(post.posted_at).toLocaleDateString(locale, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          }),
                        })}
                      </span>
                    </div>
                  </div>
                  <a
                    href={post.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="button-outline text-xs"
                  >
                    {t("viewPost")}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
