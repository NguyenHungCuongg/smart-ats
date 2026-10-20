// A Job's Upload Batches as the API sends them, and why an upload was refused (FR-A1.2).

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

const REASONS: Record<string, string> = {
  TOO_LARGE: "vượt quá 10 MB",
  UNSUPPORTED_TYPE: "không phải PDF hoặc DOCX",
};

const STATUS_ERRORS: Record<number, string> = {
  413: "Mỗi lần tải lên tối đa 50 CV, mỗi file tối đa 10 MB.",
  415: "CV phải là file PDF hoặc DOCX.",
  422: "Cần xác nhận cơ sở xử lý dữ liệu và chọn ít nhất một file CV.",
};

/** What to tell the Recruiter when the API refused a batch with `status` and `detail`. */
export function uploadError(status: number, detail: unknown): string {
  // The API refuses the whole batch and names each file at fault; Caddy's 413 names none.
  const files = (detail as { files?: { file_name: string; reason: string }[] } | undefined)?.files;
  if (files?.length) {
    const named = files.map((f) => `${f.file_name} (${REASONS[f.reason] ?? f.reason})`);
    return `Không tải lên được: ${named.join(", ")}. Bỏ hoặc sửa các file này rồi tải lên lại.`;
  }
  return STATUS_ERRORS[status] ?? "Không tải lên được CV. Thử lại.";
}
