// A Job's Upload Batches as the API sends them, and why an upload was refused (FR-A1.2).

import type { Translator } from "../../i18n/messages";

export type Item = {
  id: string;
  file_name: string;
  status: "PENDING" | "SUCCEEDED" | "FAILED";
  dedupe: "EXISTING_CANDIDATE" | "CV_REPLACED" | "ALREADY_APPLIED" | null;
  error_code: string | null;
  error_message: string | null;
};

export type Batch = {
  id: string;
  status: "PROCESSING" | "COMPLETED";
  total: number;
  /** Items done, failed ones included. */
  processed: number;
  failed: number;
  created_at: string;
  items: Item[];
};

const STATUS_ERRORS: Record<number, "limits" | "unsupported" | "consentAndFiles"> = {
  413: "limits",
  415: "unsupported",
  422: "consentAndFiles",
};

/** What to tell the Recruiter when the API refused a batch with `status` and `detail`. */
export function uploadError(t: Translator<"uploads">, status: number, detail: unknown): string {
  // The API refuses the whole batch and names each file at fault; Caddy's 413 names none.
  const files = (detail as { files?: { file_name: string; reason: string }[] } | undefined)?.files;
  if (files?.length) {
    const reason = (code: string) =>
      code === "TOO_LARGE" || code === "UNSUPPORTED_TYPE" ? t(`reason.${code}`) : code;
    const named = files.map((f) => `${f.file_name} (${reason(f.reason)})`);
    return t("rejectedFiles", { files: named.join(", ") });
  }
  return t(STATUS_ERRORS[status] ?? "failed");
}
