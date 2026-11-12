"use client";

import { useLocale, useTranslations } from "next-intl";
import { type DragEvent, type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";
import { type Batch, type Item, uploadError } from "../uploads";

// The item errors the catalog words (uploads.itemError); any other reads as a failure, never
// as the API's own message, which is English for developers.
const ITEM_ERRORS = [
  "NO_TEXT",
  "ENCRYPTED_PDF",
  "DOCX_TOO_LARGE",
  "UNREADABLE",
  "UNSUPPORTED_FORMAT",
  "UNPRICED_MODEL",
  "PARSE_FAILED",
  "STUCK",
  "LLM_UNAVAILABLE",
] as const;

const ACCEPT = ".pdf,.docx";

/** Upload CVs into the Job as Upload Batches (FR-A1.2) and follow their parses; the Kanban
 * Board shows the Applications they create. Only for those who may write to the Job. */
export function Uploads({ jobId }: { jobId: string }) {
  const t = useTranslations("uploads");
  const [batches, setBatches] = useState<Batch[]>([]);
  // Bumped to reload the batches.
  const [version, setVersion] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<number | null>(null);
  // The refusal, worded at render in the language shown.
  const [refused, setRefused] = useState<{ status: number; detail: unknown } | null>(null);

  useEffect(() => {
    apiFetch(`/api/jobs/${jobId}/uploads`).then(async (r) => r.ok && setBatches(await r.json()));
  }, [jobId, version]);
  // Each finished item moves its batch's x/y on (NFR-USE-02).
  useProgressEvents(
    "upload.item",
    (data) => {
      if ((data as { job_id: string }).job_id === jobId) setVersion((v) => v + 1);
    },
    () => setVersion((v) => v + 1),
  );

  /** Send files as one Upload Batch; true once the API took them. */
  async function send(batch: File[]): Promise<boolean> {
    const body = new FormData();
    for (const file of batch) body.append("files", file);
    body.set("consent_confirmed", String(consent));
    setPending(true);
    const response = await apiFetch(`/api/jobs/${jobId}/uploads`, { method: "POST", body });
    setPending(false);
    if (response.status === 401) {
      window.location.replace("/login");
      return false;
    }
    if (!response.ok) {
      const detail = await response
        .json()
        .then((b) => b.detail)
        .catch(() => undefined);
      setRefused({ status: response.status, detail });
      return false;
    }
    setRefused(null);
    // Each upload is attested afresh.
    setConsent(false);
    setVersion((v) => v + 1);
    return true;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (await send(files)) {
      form.reset();
      setFiles([]);
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    setFiles([...event.dataTransfer.files]);
  }

  async function retryFailed(itemId: string) {
    setRetryingId(itemId);
    const response = await apiFetch(`/api/jobs/${jobId}/uploads/items/${itemId}/retry`, {
      method: "POST",
    });
    setRetryingId(null);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      setRetryError(null);
      setVersion((v) => v + 1);
    } else {
      setRetryError(response.status);
    }
  }

  return (
    <section className="flex flex-col gap-4 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">{t("title")}</h2>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-8 text-center has-focus-visible:ring-2 has-focus-visible:ring-ring-focus ${
            dragging
              ? "border-ink-deep bg-surface-press-light"
              : "border-hairline-cool bg-surface-canvas-light"
          }`}
        >
          <span className="font-medium">{t("drop")}</span>
          <span className="text-sm">{t("accepted")}</span>
          <input
            type="file"
            multiple
            accept={ACCEPT}
            onChange={(e) => setFiles([...(e.target.files ?? [])])}
            className="sr-only"
          />
        </label>
        {files.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{t("chosen", { count: files.length })}</span>
            <ul aria-label={t("chosenList")} className="flex flex-wrap gap-x-3 font-mono text-sm">
              {files.map((file, i) => (
                <li key={i}>{file.name}</li>
              ))}
            </ul>
          </div>
        )}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1"
          />
          {t("consent")}
        </label>
        {refused && <p role="alert">{uploadError(t, refused.status, refused.detail)}</p>}
        <button
          type="submit"
          disabled={pending || !consent || files.length === 0}
          className="self-start button-outline"
        >
          {t("submit")}
        </button>
      </form>

      {retryError !== null && (
        <p role="alert">{t(retryError === 402 ? "budgetExceeded" : "retryItemFailed")}</p>
      )}
      {batches.map((batch) => (
        <BatchProgress
          key={batch.id}
          batch={batch}
          canRetry={consent && !pending}
          // Re-uploading a file makes a new batch of it (FR-A1.2).
          onRetry={(file) => send([file])}
          retryingId={retryingId}
          onRetryFailed={retryFailed}
        />
      ))}
    </section>
  );
}

/** One Upload Batch: its x/y while it runs, and each item with its outcome. */
export function BatchProgress({
  batch,
  canRetry,
  onRetry,
  retryingId,
  onRetryFailed,
}: {
  batch: Batch;
  /** Whether a failed file may be uploaded again now: it needs the attestation too. */
  canRetry: boolean;
  onRetry: (file: File) => void;
  retryingId: string | null;
  onRetryFailed: (itemId: string) => void;
}) {
  const t = useTranslations("uploads");
  const locale = useLocale();
  const running = batch.status === "PROCESSING";
  const needsReupload = batch.items.some(
    (item) => item.status === "FAILED" && item.error_code !== "LLM_UNAVAILABLE",
  );
  const itemError = (item: Item) => {
    const code = ITEM_ERRORS.find((known) => known === item.error_code);
    return code ? t(`itemError.${code}`) : t("itemFailed");
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">
          {t("batchAt", { at: new Date(batch.created_at).toLocaleString(locale) })}
        </span>
        <span role={running ? "status" : undefined}>
          {t("processed", { processed: batch.processed, total: batch.total })}
          {batch.failed > 0 && ` · ${t("failedCount", { count: batch.failed })}`}
        </span>
        {!running && <Badge>{t("done")}</Badge>}
      </div>
      {running && (
        <div
          role="progressbar"
          aria-label={t("progress")}
          aria-valuemin={0}
          aria-valuemax={batch.total}
          aria-valuenow={batch.processed}
          className="h-1 rounded-xs bg-hairline-cloud"
        >
          <div
            className="h-full rounded-xs bg-primary"
            style={{ width: `${(100 * batch.processed) / batch.total}%` }}
          />
        </div>
      )}
      {needsReupload && !canRetry && <p className="text-sm">{t("retryHint")}</p>}
      <ul aria-label={t("batchFiles")} className="flex flex-col divide-y divide-hairline-cloud">
        {batch.items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <span className="font-mono text-sm">{item.file_name}</span>
            <span className="text-sm">{t(`itemStatus.${item.status}`)}</span>
            {item.dedupe && <Badge>{t(`dedupe.${item.dedupe}`)}</Badge>}
            {item.status === "FAILED" &&
              (item.error_code === "LLM_UNAVAILABLE" ? (
                <>
                  <button
                    type="button"
                    disabled={retryingId === item.id}
                    aria-label={t("retryFailedFile", { file: item.file_name })}
                    onClick={() => onRetryFailed(item.id)}
                    className="ml-auto button-outline"
                  >
                    {t("retryFailed")}
                  </button>
                  <span className="w-full text-sm">
                    <code className="font-mono">{item.error_code}</code>: {itemError(item)}
                  </span>
                </>
              ) : (
                <>
                  <label className="ml-auto cursor-pointer button-outline has-focus-visible:ring-2 has-focus-visible:ring-ring-focus has-disabled:cursor-default has-disabled:border-hairline-cloud has-disabled:bg-hairline-cloud has-disabled:text-accent-violet-mid">
                    {t("retry")}
                    <input
                      type="file"
                      accept={ACCEPT}
                      disabled={!canRetry}
                      aria-label={t("retryFile", { file: item.file_name })}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (file) onRetry(file);
                      }}
                      className="sr-only"
                    />
                  </label>
                  <span className="w-full text-sm">
                    <code className="font-mono">{item.error_code}</code>: {itemError(item)}{" "}
                    {t("fixAndRetry")}
                  </span>
                </>
              ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
