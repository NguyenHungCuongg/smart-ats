"use client";

import { type ReactNode, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { useProgressEvents } from "../../events";
import type { Job } from "../criteria";
import { type Claim, type ScoreResult, type ScoringRun, scoreBlocker } from "../scoring";

const START_ERRORS: Record<number, string> = {
  409: "Job chưa đủ điều kiện chấm điểm hoặc đang được chấm.",
  503: "Model AI chưa có trong bảng giá nên chưa được gọi. Liên hệ quản trị viên.",
};

const RESULT_ERRORS: Record<string, string> = {
  NO_TEXT: "File CV hoặc JD không có lớp văn bản.",
  ENCRYPTED_PDF: "File CV hoặc JD được đặt mật khẩu.",
  DOCX_TOO_LARGE: "File DOCX của CV hoặc JD quá lớn khi giải nén.",
  UNREADABLE: "File CV hoặc JD bị hỏng, không đọc được.",
  UNSUPPORTED_FORMAT: "Định dạng file CV hoặc JD không được hỗ trợ.",
  READ_FAILED: "Không đọc được file CV hoặc JD.",
  SCORING_FAILED: "Lời gọi AI bị lỗi.",
  STUCK: "Hệ thống chưa chấm được Application này sau nhiều lần thử.",
};

const RUN_STATUSES: Record<ScoringRun["status"], string> = {
  RUNNING: "Đang chạy",
  COMPLETED: "Hoàn tất",
  PARTIAL: "Hoàn tất, có lỗi",
};

const score = (value: number | null) =>
  value === null ? "—" : value.toLocaleString("vi-VN", { maximumFractionDigits: 2 });

/** Start a Scoring Run of the Job and show the Fit-Gap Report of each Application (FR-A1.3). */
export function Scoring({ job, applications }: { job: Job; applications: number }) {
  const [run, setRun] = useState<ScoringRun | null>(null);
  // The run shown: set by a start before its first load, so its events are not dropped.
  const [runId, setRunId] = useState<string | null>(null);
  // Bumped to reload the run.
  const [version, setVersion] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/api/jobs/${job.id}/scoring-runs/latest`).then(async (response) => {
      if (!response.ok) return; // 404: never scored
      const latest: ScoringRun = await response.json();
      setRun(latest);
      setRunId(latest.id);
    });
  }, [job.id, version]);
  useProgressEvents("scoring.result", (data) => {
    // A task of an older, expired run may still finish: it must not reload over this one.
    if ((data as { run_id: string }).run_id === runId) setVersion((v) => v + 1);
  });
  // A new CV may replace a scored one.
  useProgressEvents("upload.item", (data) => {
    if ((data as { job_id: string }).job_id === job.id) setVersion((v) => v + 1);
  });

  async function onStart() {
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}/scoring-runs`, { method: "POST" });
    setPending(false);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      setError(null);
      setRunId((await response.json()).run_id);
    } else {
      setError(START_ERRORS[response.status] ?? "Không bắt đầu chấm điểm được. Thử lại.");
    }
    setVersion((v) => v + 1);
  }

  const blocker = scoreBlocker(job, applications, run);
  return (
    <section className="flex flex-col gap-4 border-t border-[#e5e7eb] pt-6">
      <h2 className="text-2xl font-medium">Chấm điểm</h2>
      {run && (
        <p className="text-sm">
          Lần chấm gần nhất: {new Date(run.created_at).toLocaleString("vi-VN")} ·{" "}
          {isExpired(run) ? "Quá hạn, có thể chấm lại" : RUN_STATUSES[run.status]} · model{" "}
          <code className="font-mono">{run.model}</code> · trọng số Technical{" "}
          {run.weights.technical}%, Soft Skills {run.weights.soft_skills}%, Experience{" "}
          {run.weights.experience}%
        </p>
      )}
      {blocker && (
        <p className="text-sm" role={run?.running ? "status" : undefined}>
          {blocker}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <button
        type="button"
        onClick={onStart}
        disabled={pending || blocker !== null}
        className="self-start rounded-lg border border-[#1f1633] px-4 py-3 text-sm font-medium tracking-[0.2px] uppercase disabled:border-[#e5e7eb] disabled:bg-[#e5e7eb] disabled:text-[rgba(255,255,255,0.72)]"
      >
        {run ? "Chấm lại" : "Chấm điểm"}
      </button>
      {run?.results.map((result) => (
        <Result key={result.application_id} result={result} expired={isExpired(run)} />
      ))}
    </section>
  );
}

/** A run left RUNNING past its time: its PENDING rows will not be scored. */
const isExpired = (run: ScoringRun) => run.status === "RUNNING" && !run.running;

const REPORT_PARTS = [
  ["strengths", "Strengths"],
  ["gaps", "Gaps"],
  ["recommendations", "Recommendations"],
] as const;

function Result({ result, expired }: { result: ScoreResult; expired: boolean }) {
  const rubric = result.rubric_grades;
  const report = result.fit_gap_report;
  const detail = result.must_have_detail;
  return (
    <article className="flex flex-col gap-4 rounded-xl border border-[#e5e7eb] bg-white p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h3 className="text-xl font-semibold">{result.full_name ?? "Ứng viên"}</h3>
        {result.cv_document_id !== result.current_cv_document_id && (
          <Badge>CV đã thay đổi sau lần chấm</Badge>
        )}
      </header>
      {result.status === "PENDING" &&
        (expired ? <p>Chưa chấm xong.</p> : <p role="status">Đang chấm…</p>)}
      {result.status === "FAILED" && (
        <p role="alert">
          {RESULT_ERRORS[result.error_code ?? ""] ?? "Không chấm được Application này."}
        </p>
      )}
      {result.status === "SCORED" && rubric && report && (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <Score label="Total" value={result.total_score} />
            <Score label="Technical Fit" value={result.technical_score} />
            <Score label="Soft-Skill Claims" value={result.soft_skills_score}>
              <Badge>Cần kiểm chứng khi phỏng vấn</Badge>
            </Score>
            <Score label="Experience Fit" value={result.experience_score} />
          </div>

          {detail && (
            <div className="flex flex-col gap-1 text-sm">
              <p className="font-medium">
                Must-have Coverage: {Math.round((result.must_have_coverage ?? 0) * 100)}% (
                {detail.matched.length}/{detail.matched.length + detail.missing.length})
              </p>
              <p>Đã khớp: {detail.matched.join(", ") || "—"}</p>
              <p>Còn thiếu: {detail.missing.join(", ") || "—"}</p>
            </div>
          )}

          <Part title="Lý do chấm từng trục">
            {(
              [
                ["technical", "Technical"],
                ["soft_skills", "Soft-Skill Claims"],
                ["experience", "Experience"],
              ] as const
            ).map(([axis, label]) => (
              <Item key={axis} claim={rubric[axis]}>
                {label} {rubric[axis].grade}/5: {rubric[axis].reason}
              </Item>
            ))}
          </Part>
          {REPORT_PARTS.map(([part, title]) => (
            <Part key={part} title={title}>
              {report[part].map((claim, i) => (
                <Item key={i} claim={claim}>
                  {claim.text}
                </Item>
              ))}
            </Part>
          ))}
        </>
      )}
    </article>
  );
}

function Score({
  label,
  value,
  children,
}: {
  label: string;
  value: number | null;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <span className="text-3xl font-semibold">{score(value)}</span>
      {children}
    </div>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-semibold">{title}</h4>
      <ul className="flex flex-col gap-2">{children}</ul>
    </div>
  );
}

/** A claim with the Evidence quoted for it, flagged when none was found in the source. */
function Item({ claim, children }: { claim: Claim; children: ReactNode }) {
  return (
    <li className="flex flex-col gap-1 text-sm">
      <span className="flex flex-wrap items-center gap-2">
        {children}
        {!claim.grounded && <Badge>Không có bằng chứng</Badge>}
      </span>
      {claim.evidence.map((quote, i) => (
        <q key={i} className="border-l-2 border-[#e5e7eb] pl-3 italic">
          {quote}
        </q>
      ))}
    </li>
  );
}

function Badge({ children }: { children: string }) {
  return (
    <span className="self-start rounded bg-[#150f23] px-2 text-[10px] font-semibold tracking-[0.25px] whitespace-nowrap text-white uppercase">
      {children}
    </span>
  );
}
