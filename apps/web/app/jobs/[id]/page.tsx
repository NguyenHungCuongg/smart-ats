"use client";

import { type FormEvent, type ReactNode, use, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { useProgressEvents } from "../../events";
import {
  type Form,
  type Job,
  LEVELS,
  WORK_MODES,
  formFromJob,
  toConfirmation,
  weightTotal,
} from "../criteria";
import { Scoring } from "./scoring";
import { Uploads } from "./uploads";

const PARSE_ERRORS: Record<string, string> = {
  NO_TEXT: "JD không có lớp văn bản (bản scan hoặc file rỗng).",
  ENCRYPTED_PDF: "PDF của JD được đặt mật khẩu.",
  DOCX_TOO_LARGE: "File DOCX của JD quá lớn khi giải nén.",
  UNREADABLE: "File JD bị hỏng, không đọc được.",
  UNSUPPORTED_FORMAT: "Định dạng file JD không được hỗ trợ.",
  UNPRICED_MODEL: "Model AI chưa có trong bảng giá nên chưa được gọi. Liên hệ quản trị viên.",
};

const INPUT =
  "rounded-md border border-[#cfcfdb] bg-white px-3 py-2 text-[#1f1633] focus:ring-2 focus:ring-[rgba(59,130,246,0.5)] focus:outline-none";
// Secondary actions read as link-on-light: one filled button per page (DESIGN.md).
const LINK_BUTTON = "font-medium text-[#1f1633] underline";

/** Follows the parse of a Job's JD, then lets the Recruiter edit and confirm the criteria. */
export default function JobPage({ params }: PageProps<"/jobs/[id]">) {
  const { id } = use(params);
  const [job, setJob] = useState<Job | null>(null);
  const [missing, setMissing] = useState(false);
  // Bumped to reload the Job.
  const [version, setVersion] = useState(0);
  const [applications, setApplications] = useState(0);

  useEffect(() => {
    apiFetch(`/api/jobs/${id}`).then(async (response) => {
      if (response.status === 401) window.location.replace("/login");
      else if (response.ok) setJob(await response.json());
      else setMissing(true);
    });
  }, [id, version]);
  // ponytail: a parse that finishes before the stream opens shows only after a reload;
  // refetch once the stream is open if parses get that fast.
  useProgressEvents("job.parsed", (data) => {
    if ((data as { job_id: string }).job_id === id) setVersion((v) => v + 1);
  });

  return (
    <main className="min-h-screen bg-white text-[#1f1633]">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        {missing ? (
          <p>Không tìm thấy Job.</p>
        ) : !job ? (
          <p>Đang tải…</p>
        ) : job.parse_status === "PENDING" ? (
          <>
            <h1 className="text-3xl font-semibold">{job.title}</h1>
            <p role="status">Đang phân tích JD…</p>
          </>
        ) : (
          // Remount on every saved or parsed version, so the form starts from it.
          <CriteriaForm
            key={`${job.parse_status}-${job.criteria_confirmed_at}`}
            job={job}
            onSaved={setJob}
          />
        )}
        {/* CVs go into any Job; only scoring needs confirmed criteria. */}
        {job && <Uploads jobId={id} onApplications={setApplications} />}
        {job && <Scoring job={job} applications={applications} />}
      </div>
    </main>
  );
}

function CriteriaForm({ job, onSaved }: { job: Job; onSaved: (job: Job) => void }) {
  const [form, setForm] = useState<Form>(() => formFromJob(job));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const total = weightTotal(form.weights);
  const review = (field: string) => job.verification?.[field] === "NEEDS_REVIEW";
  const set = (changes: Partial<Form>) => setForm({ ...form, ...changes });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}/criteria`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toConfirmation(form)),
    });
    setPending(false);
    if (response.ok) return onSaved(await response.json());
    setError(
      response.status === 409
        ? "JD vẫn đang được phân tích."
        : "Không lưu được criteria. Kiểm tra lại các trường.",
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Xác nhận criteria</h1>
      {job.parse_status === "FAILED" && (
        <p role="alert">
          {PARSE_ERRORS[job.parse_error ?? ""] ?? "Không phân tích được JD."} Hãy nhập criteria thủ
          công.
        </p>
      )}
      {job.criteria_confirmed_at && (
        <p role="status">
          Đã xác nhận lúc {new Date(job.criteria_confirmed_at).toLocaleString("vi-VN")}.
        </p>
      )}
      {job.verification && (
        <p className="text-sm">Trường gắn “Cần kiểm tra” không tìm thấy nguyên văn trong JD.</p>
      )}

      <Field label="Chức danh" review={review("title")}>
        <input
          required
          maxLength={200}
          value={form.title}
          onChange={(e) => set({ title: e.target.value })}
          className={INPUT}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Cấp bậc" review={review("level")}>
          <select
            value={form.level}
            onChange={(e) => set({ level: e.target.value as Form["level"] })}
            className={INPUT}
          >
            {LEVELS.map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </Field>
        <Field label="Hình thức làm việc" review={review("work_mode")}>
          <select
            value={form.work_mode}
            onChange={(e) => set({ work_mode: e.target.value as Form["work_mode"] })}
            className={INPUT}
          >
            <option value="">Không nêu</option>
            {WORK_MODES.map((mode) => (
              <option key={mode}>{mode}</option>
            ))}
          </select>
        </Field>
        <Field label="Phòng ban" review={review("department")}>
          <input
            maxLength={200}
            value={form.department}
            onChange={(e) => set({ department: e.target.value })}
            className={INPUT}
          />
        </Field>
        <Field label="Địa điểm" review={review("location")}>
          <input
            maxLength={200}
            value={form.location}
            onChange={(e) => set({ location: e.target.value })}
            className={INPUT}
          />
        </Field>
      </div>

      <Group label="Kỹ năng" review={review("skills")}>
        {form.skills.map((skill, i) => (
          <div key={i} className="flex items-center gap-3">
            <input
              aria-label="Tên kỹ năng"
              maxLength={200}
              value={skill.name}
              onChange={(e) =>
                set({ skills: form.skills.with(i, { ...skill, name: e.target.value }) })
              }
              className={`${INPUT} flex-1`}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={skill.must_have}
                onChange={(e) =>
                  set({ skills: form.skills.with(i, { ...skill, must_have: e.target.checked }) })
                }
              />
              Must-have
            </label>
            <button
              type="button"
              onClick={() => set({ skills: form.skills.toSpliced(i, 1) })}
              className={LINK_BUTTON}
            >
              Xóa
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => set({ skills: [...form.skills, { name: "", must_have: false }] })}
          className={`${LINK_BUTTON} self-start`}
        >
          Thêm kỹ năng
        </button>
      </Group>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Số năm kinh nghiệm tối thiểu" review={review("min_years_experience")}>
          <input
            type="number"
            min={0}
            max={60}
            step="any"
            value={form.min_years_experience}
            onChange={(e) => set({ min_years_experience: e.target.value })}
            className={INPUT}
          />
        </Field>
        <Field label="Dải lương" review={review("salary_range")}>
          <input
            maxLength={200}
            value={form.salary_range}
            onChange={(e) => set({ salary_range: e.target.value })}
            className={INPUT}
          />
        </Field>
      </div>
      <Field label="Học vấn" review={review("education")}>
        <input
          maxLength={2000}
          value={form.education}
          onChange={(e) => set({ education: e.target.value })}
          className={INPUT}
        />
      </Field>
      <Field label="Trách nhiệm chính (mỗi dòng một ý)" review={review("responsibilities")}>
        <textarea
          rows={5}
          value={form.responsibilities}
          onChange={(e) => set({ responsibilities: e.target.value })}
          className={INPUT}
        />
      </Field>

      <Group label="Trọng số (%)">
        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["technical", "Technical Fit"],
              ["soft_skills", "Soft Skills"],
              ["experience", "Experience"],
            ] as const
          ).map(([axis, label]) => (
            <Field key={axis} label={label}>
              <input
                type="number"
                min={0}
                max={100}
                required
                value={form.weights[axis]}
                onChange={(e) =>
                  set({ weights: { ...form.weights, [axis]: Math.round(Number(e.target.value)) } })
                }
                className={INPUT}
              />
            </Field>
          ))}
        </div>
        <p aria-live="polite" className={total === 100 ? "text-sm" : "text-sm font-semibold"}>
          Tổng: {total}%{total !== 100 && " (phải bằng 100%)"}
        </p>
      </Group>

      {error && <p role="alert">{error}</p>}
      <button
        type="submit"
        disabled={pending || total !== 100}
        className="self-start rounded-lg bg-[#150f23] px-4 py-3 text-sm font-bold tracking-[0.2px] text-white uppercase disabled:bg-[#e5e7eb] disabled:text-[rgba(255,255,255,0.72)]"
      >
        Xác nhận criteria
      </button>
    </form>
  );
}

function ReviewBadge() {
  return (
    <span className="rounded bg-[#150f23] px-2 text-[10px] font-semibold tracking-[0.25px] text-white uppercase">
      Cần kiểm tra
    </span>
  );
}

const reviewed = (review?: boolean) => (review ? "border-l-4 border-[#fa7faa] pl-3" : "");

/** One labelled input; a Needs review field is highlighted (FR-A1.1). */
function Field({
  label,
  review,
  children,
}: {
  label: string;
  review?: boolean;
  children: ReactNode;
}) {
  return (
    <label className={`flex flex-col gap-1 ${reviewed(review)}`}>
      <span className="flex items-center gap-2 font-medium">
        {label}
        {review && <ReviewBadge />}
      </span>
      {children}
    </label>
  );
}

/** Several inputs under one caption. */
function Group({
  label,
  review,
  children,
}: {
  label: string;
  review?: boolean;
  children: ReactNode;
}) {
  return (
    <fieldset className={`flex flex-col gap-2 ${reviewed(review)}`}>
      <legend className="flex items-center gap-2 font-medium">
        {label}
        {review && <ReviewBadge />}
      </legend>
      {children}
    </fieldset>
  );
}
