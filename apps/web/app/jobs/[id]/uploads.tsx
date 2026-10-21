"use client";

import { type DragEvent, type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";
import { type Batch, type Item, uploadError } from "../uploads";

type Application = {
  id: string;
  full_name: string | null;
  /** Absent for a Reviewer, who sees no contact details (SRS §2.1). */
  email?: string | null;
  stage: string;
  file_name: string;
};

const ITEM_ERRORS: Record<string, string> = {
  NO_TEXT: "CV không có lớp văn bản (bản scan hoặc file rỗng).",
  ENCRYPTED_PDF: "PDF được đặt mật khẩu.",
  DOCX_TOO_LARGE: "File DOCX quá lớn khi giải nén.",
  UNREADABLE: "File bị hỏng, không đọc được.",
  UNSUPPORTED_FORMAT: "Định dạng file không được hỗ trợ.",
  UNPRICED_MODEL: "Model AI chưa có trong bảng giá nên chưa được gọi. Liên hệ quản trị viên.",
  PARSE_FAILED: "Không phân tích được CV.",
  STUCK: "Hệ thống chưa xử lý được CV sau nhiều lần thử.",
};

const STATUSES: Record<Item["status"], string> = {
  PENDING: "Đang xử lý…",
  SUCCEEDED: "Thành công",
  FAILED: "Lỗi",
};

const DEDUPES: Record<NonNullable<Item["dedupe"]>, string> = {
  EXISTING_CANDIDATE: "Ứng viên đã có",
  CV_REPLACED: "Đã thay CV",
  ALREADY_APPLIED: "Đã ứng tuyển",
};

const ACCEPT = ".pdf,.docx";

/** Upload CVs into the Job as Upload Batches (FR-A1.2), follow their parses, and list the Job's
 * Applications. */
export function Uploads({
  jobId,
  editable,
  onApplications,
}: {
  jobId: string;
  /** Whether CVs may go in: not for a Reviewer, nor into an archived Job. */
  editable: boolean;
  /** Told how many Applications the Job has, after each load. */
  onApplications: (count: number) => void;
}) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  // Bumped to reload both lists.
  const [version, setVersion] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Only those who upload follow the batches.
    if (editable) {
      apiFetch(`/api/jobs/${jobId}/uploads`).then(async (r) => r.ok && setBatches(await r.json()));
    }
    apiFetch(`/api/jobs/${jobId}/applications`).then(async (r) => {
      if (!r.ok) return;
      const list: Application[] = await r.json();
      setApplications(list);
      onApplications(list.length);
    });
  }, [jobId, editable, version, onApplications]);
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
      setError(uploadError(response.status, detail));
      return false;
    }
    setError(null);
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

  const contact = applications.some((a) => "email" in a);
  return (
    <section className="flex flex-col gap-4 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">Ứng viên</h2>
      {editable && (
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
            <span className="font-medium">Kéo-thả CV vào đây hoặc bấm để chọn</span>
            <span className="text-sm">PDF hoặc DOCX, tối đa 50 file mỗi lần, mỗi file 10 MB</span>
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
              <span className="text-sm font-medium">Đã chọn {files.length} file</span>
              <ul aria-label="File đã chọn" className="flex flex-wrap gap-x-3 font-mono text-sm">
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
            Tôi xác nhận đã có sự đồng ý của ứng viên hoặc cơ sở pháp lý hợp lệ để xử lý dữ liệu cá
            nhân trong các CV này.
          </label>
          {error && <p role="alert">{error}</p>}
          <button
            type="submit"
            disabled={pending || !consent || files.length === 0}
            className="self-start button-outline"
          >
            Tải CV lên
          </button>
        </form>
      )}

      {batches.map((batch) => (
        <BatchProgress
          key={batch.id}
          batch={batch}
          canRetry={consent && !pending}
          // Re-uploading a file makes a new batch of it (FR-A1.2).
          onRetry={(file) => send([file])}
        />
      ))}

      <h3 className="text-xl font-semibold">Application ({applications.length})</h3>
      {applications.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline-cloud">
              <th className="py-2 font-medium">Họ tên</th>
              {contact && <th className="py-2 font-medium">Email</th>}
              <th className="py-2 font-medium">Stage</th>
              <th className="py-2 font-medium">CV</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((a) => (
              <tr key={a.id} className="border-b border-hairline-cloud">
                <td className="py-2">{a.full_name ?? "—"}</td>
                {contact && <td className="py-2">{a.email ?? "—"}</td>}
                <td className="py-2">
                  <Badge>{a.stage}</Badge>
                </td>
                <td className="py-2 font-mono">{a.file_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** One Upload Batch: its x/y while it runs, and each item with its outcome. */
function BatchProgress({
  batch,
  canRetry,
  onRetry,
}: {
  batch: Batch;
  /** Whether a failed file may be uploaded again now: it needs the attestation too. */
  canRetry: boolean;
  onRetry: (file: File) => void;
}) {
  const running = batch.status === "PROCESSING";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">
          Lô tải lên lúc {new Date(batch.created_at).toLocaleString("vi-VN")}
        </span>
        <span role={running ? "status" : undefined}>
          Đã xử lý {batch.processed}/{batch.total} CV
          {batch.failed > 0 && ` · ${batch.failed} lỗi`}
        </span>
        {!running && <Badge>Hoàn tất</Badge>}
      </div>
      {running && (
        <div
          role="progressbar"
          aria-label="Tiến độ lô tải lên"
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
      {batch.failed > 0 && !canRetry && (
        <p className="text-sm">Đánh dấu ô xác nhận ở trên để tải lại từng file lỗi.</p>
      )}
      <ul aria-label="File trong lô" className="flex flex-col divide-y divide-hairline-cloud">
        {batch.items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <span className="font-mono text-sm">{item.file_name}</span>
            <span className="text-sm">{STATUSES[item.status]}</span>
            {item.dedupe && <Badge>{DEDUPES[item.dedupe]}</Badge>}
            {item.status === "FAILED" && (
              <>
                <label className="ml-auto cursor-pointer button-outline has-focus-visible:ring-2 has-focus-visible:ring-ring-focus has-disabled:cursor-default has-disabled:border-hairline-cloud has-disabled:bg-hairline-cloud has-disabled:text-accent-violet-mid">
                  Tải lại
                  <input
                    type="file"
                    accept={ACCEPT}
                    disabled={!canRetry}
                    aria-label={`Tải lại ${item.file_name}`}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file) onRetry(file);
                    }}
                    className="sr-only"
                  />
                </label>
                <span className="w-full text-sm">
                  <code className="font-mono">{item.error_code}</code>:{" "}
                  {ITEM_ERRORS[item.error_code ?? ""] ?? item.error_message} Sửa file rồi tải lại.
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
