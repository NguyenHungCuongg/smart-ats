"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { type ActivityEntry, type ActivityPage, actorBadge, formatActivity } from "../activity";

type FetchResult =
  { status: "unauthorized" } | { status: "failed" } | { status: "ok"; page: ActivityPage };

async function fetchTimelinePage(url: string): Promise<FetchResult> {
  const response = await apiFetch(url);
  if (response.status === 401) return { status: "unauthorized" };
  if (!response.ok) return { status: "failed" };
  return { status: "ok", page: (await response.json()) as ActivityPage };
}

function handleTimelineResult(
  result: FetchResult,
  setFailed: (failed: boolean) => void,
  onPage: (page: ActivityPage) => void,
) {
  if (result.status === "unauthorized") window.location.replace("/login");
  else if (result.status === "failed") setFailed(true);
  else {
    setFailed(false);
    onPage(result.page);
  }
}

/** Presentational Activity Timeline list with loading, empty, error, and pagination controls. */
export function ActivityList({
  items,
  nextCursor,
  loadingMore,
  failed,
  onLoadMore,
}: {
  items: ActivityEntry[] | null;
  nextCursor: string | null;
  loadingMore: boolean;
  failed: boolean;
  onLoadMore: () => void;
}) {
  const t = useTranslations("activity");
  const statusName = useTranslations("lifecycle.status");
  const jobField = useTranslations("job");
  const stageName = useTranslations("pipeline.stage");
  const sourceName = useTranslations("pipeline.source");
  const locale = useLocale();
  const translators = { t, statusName, jobField, stageName, sourceName, locale };

  if (failed) {
    return <p role="alert">{t("loadFailed")}</p>;
  }
  if (!items) {
    return (
      <div
        aria-busy="true"
        aria-label={t("loading")}
        className="h-16 animate-pulse rounded-md bg-hairline-cloud"
      />
    );
  }
  if (items.length === 0) {
    return <p className="text-sm">{t("empty")}</p>;
  }

  return (
    <>
      <ol className="flex flex-col gap-3">
        {items.map((entry) => {
          const badge = actorBadge(entry.actor_type, t);
          return (
            <li
              key={entry.id}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-hairline-cloud pb-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                {badge && <Badge>{badge}</Badge>}
                <span>{formatActivity(entry, translators)}</span>
              </div>
              <time dateTime={entry.created_at} className="font-mono text-xs">
                {new Date(entry.created_at).toLocaleString(locale)}
              </time>
            </li>
          );
        })}
      </ol>
      {nextCursor && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loadingMore}
          className="button-outline self-start"
        >
          {t("loadMore")}
        </button>
      )}
    </>
  );
}

/** Fetches and paginates an entity's Activity Timeline newest first (FR-A3.3). */
export function ActivityFeed({
  endpoint,
  refreshKey = 0,
}: {
  endpoint: string;
  refreshKey?: number;
}) {
  const [items, setItems] = useState<ActivityEntry[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchTimelinePage(endpoint).then((result) => {
      if (!active) return;
      handleTimelineResult(result, setFailed, (page) => {
        setItems(page.items);
        setNextCursor(page.next_cursor);
      });
    });
    return () => {
      active = false;
    };
  }, [endpoint, refreshKey]);

  async function onLoadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    const separator = endpoint.includes("?") ? "&" : "?";
    const result = await fetchTimelinePage(
      `${endpoint}${separator}cursor=${encodeURIComponent(nextCursor)}`,
    );
    setLoadingMore(false);
    handleTimelineResult(result, setFailed, (page) => {
      setItems((prev) => [...(prev ?? []), ...page.items]);
      setNextCursor(page.next_cursor);
    });
  }

  return (
    <ActivityList
      items={items}
      nextCursor={nextCursor}
      loadingMore={loadingMore}
      failed={failed}
      onLoadMore={onLoadMore}
    />
  );
}

/** The Job's Activity Timeline, newest first, with keyset pagination for older pages (FR-A3.3). */
export function Activity({ jobId, refreshKey = 0 }: { jobId: string; refreshKey?: number }) {
  const t = useTranslations("activity");
  return (
    <section className="flex flex-col gap-3 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">{t("title")}</h2>
      <ActivityFeed endpoint={`/api/jobs/${jobId}/timeline`} refreshKey={refreshKey} />
    </section>
  );
}
