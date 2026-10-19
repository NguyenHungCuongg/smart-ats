"use client";

import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";

type Item = {
  id: string;
  file_name: string;
  status: "PENDING" | "SUCCEEDED" | "FAILED";
  dedupe: "EXISTING_CANDIDATE" | "CV_REPLACED" | "ALREADY_APPLIED" | null;
  error_code: string | null;
  error_message: string | null;
};

type Application = {
  id: string;
  full_name: string | null;
  email: string | null;
  stage: string;
  file_name: string;
};

const UPLOAD_ERRORS: Record<number, string> = {
  413: "File CV vượt quá 10 MB.",
  415: "CV phải là file PDF hoặc DOCX.",
  422: "Cần xác nhận cơ sở xử lý dữ liệu và chọn một file CV.",
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

/** Upload one CV into the Job (FR-A1.2), follow its parse, and list the Job's Applications. */
export function Uploads({
  jobId,
  onApplications,
}: {
  jobId: string;
  /** Told how many Applications the Job has, after each load. */
  onApplications: (count: number) => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  // Bumped to reload both lists.
  const [version, setVersion] = useState(0);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/api/jobs/${jobId}/uploads`).then(async (r) => r.ok && setItems(await r.json()));
    apiFetch(`/api/jobs/${jobId}/applications`).then(async (r) => {
      if (!r.ok) return;
      const list: Application[] = await r.json();
      setApplications(list);
      onApplications(list.length);
    });
  }, [jobId, version, onApplications]);
  useProgressEvents(
    "upload.item",
    (data) => {
      if ((data as { job_id: string }).job_id === jobId) setVersion((v) => v + 1);
    },
    () => setVersion((v) => v + 1),
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const body = new FormData(form);
    body.set("consent_confirmed", String(consent));
    setPending(true);
    const response = await apiFetch(`/api/jobs/${jobId}/uploads`, { method: "POST", body });
    setPending(false);
    if (response.status === 401) return window.location.replace("/login");
    if (!response.ok) {
      return setError(UPLOAD_ERRORS[response.status] ?? "Không tải lên được CV. Thử lại.");
    }
    setError(null);
    form.reset();
    setConsent(false);
    setVersion((v) => v + 1);
  }

  return (
    <section className="flex flex-col gap-4 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">Ứng viên</h2>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-medium">File CV (PDF, DOCX, tối đa 10 MB)</span>
          <input name="file" type="file" required accept=".pdf,.docx" className="text-input" />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1"
          />
          Tôi xác nhận đã có sự đồng ý của ứng viên hoặc cơ sở pháp lý hợp lệ để xử lý dữ liệu cá
          nhân trong CV này.
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={pending || !consent} className="self-start button-outline">
          Tải CV lên
        </button>
      </form>

      {items.length > 0 && (
        <ul aria-label="File đã tải lên" className="flex flex-col divide-y divide-hairline-cloud">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="font-mono text-sm">{item.file_name}</span>
              <span className="text-sm" role={item.status === "PENDING" ? "status" : undefined}>
                {STATUSES[item.status]}
              </span>
              {item.dedupe && <Badge>{DEDUPES[item.dedupe]}</Badge>}
              {item.status === "FAILED" && (
                <span className="w-full text-sm">
                  {ITEM_ERRORS[item.error_code ?? ""] ?? item.error_message} Sửa file rồi tải lên
                  lại.
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 className="text-xl font-semibold">Application ({applications.length})</h3>
      {applications.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline-cloud">
              <th className="py-2 font-medium">Họ tên</th>
              <th className="py-2 font-medium">Email</th>
              <th className="py-2 font-medium">Stage</th>
              <th className="py-2 font-medium">CV</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((a) => (
              <tr key={a.id} className="border-b border-hairline-cloud">
                <td className="py-2">{a.full_name ?? "—"}</td>
                <td className="py-2">{a.email ?? "—"}</td>
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
