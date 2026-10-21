"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import type { Job } from "../criteria";

export function PublicApplySection({ job, onSaved }: { job: Job; onSaved: (job: Job) => void }) {
  const t = useTranslations("jobPublicApply");
  const [pending, setPending] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => setCopied(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [copied]);

  const publicUrl =
    typeof window !== "undefined" && job.public_slug
      ? `${window.location.origin}/apply/${job.public_slug}`
      : "";

  async function toggle() {
    setPending(true);
    setError(false);
    const response = await apiFetch(`/api/jobs/${job.id}/public-apply`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !job.public_apply_enabled }),
    });
    setPending(false);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      onSaved(await response.json());
    } else {
      setError(true);
    }
  }

  async function copyToClipboard() {
    if (!publicUrl) return;
    try {
      await navigator.clipboard.writeText(publicUrl);
      setCopied(true);
    } catch {
      // Ignore clipboard write failures
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-hairline-cloud bg-surface-night/10 p-4 dark:border-hairline-violet">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{t("title")}</span>
          <Badge>{job.public_apply_enabled ? t("enabled") : t("disabled")}</Badge>
        </div>
        <button
          type="button"
          disabled={pending}
          onClick={toggle}
          className="button-outline text-sm"
        >
          {job.public_apply_enabled ? t("turnOff") : t("turnOn")}
        </button>
      </div>
      <p className="text-sm opacity-80">{t("description")}</p>

      {job.public_apply_enabled && (
        <div className="flex flex-col gap-2">
          {job.status !== "PUBLISHED" && (
            <p className="text-xs text-accent-pink">{t("closedWarning")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              readOnly
              value={publicUrl}
              className="flex-1 text-input font-mono text-sm"
            />
            <button
              type="button"
              onClick={copyToClipboard}
              className="button-primary text-sm whitespace-nowrap"
            >
              {copied ? t("copied") : t("copyLink")}
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-accent-pink">
          {t("toggleFailed")}
        </p>
      )}
    </div>
  );
}
