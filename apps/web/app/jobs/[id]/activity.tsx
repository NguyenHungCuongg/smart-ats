"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { type ActivityEntry, type ActivityPage, actorBadge, formatActivity } from "../activity";

/** The Job's Activity Timeline, newest first, with keyset pagination for older pages (FR-A3.3). */
export function Activity({ jobId, refreshKey = 0 }: { jobId: string; refreshKey?: number }) {
  const t = useTranslations("activity");
  const statusName = useTranslations("lifecycle.status");
  const jobField = useTranslations("job");
  const locale = useLocale();
  const [items, setItems] = useState<ActivityEntry[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    let active = true;
    apiFetch(`/api/jobs/${jobId}/timeline`).then(async (response) => {
      if (!active || !response.ok) return;
      const page = (await response.json()) as ActivityPage;
      if (!active) return;
      setItems(page.items);
      setNextCursor(page.next_cursor);
    });
    return () => {
      active = false;
    };
  }, [jobId, refreshKey]);

  async function onLoadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    const response = await apiFetch(
      `/api/jobs/${jobId}/timeline?cursor=${encodeURIComponent(nextCursor)}`,
    );
    setLoadingMore(false);
    if (!response.ok) return;
    const page = (await response.json()) as ActivityPage;
    setItems((prev) => [...(prev ?? []), ...page.items]);
    setNextCursor(page.next_cursor);
  }

  return (
    <section className="flex flex-col gap-3 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">{t("title")}</h2>
      {!items ? (
        <div
          aria-busy="true"
          aria-label={t("loading")}
          className="h-16 animate-pulse rounded-md bg-hairline-cloud"
        />
      ) : items.length === 0 ? (
        <p className="text-sm">{t("empty")}</p>
      ) : (
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
                    <span>{formatActivity(entry, t, statusName, jobField)}</span>
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
              className="self-start button-outline"
            >
              {t("loadMore")}
            </button>
          )}
        </>
      )}
    </section>
  );
}
