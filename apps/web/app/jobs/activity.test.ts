import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { type ActivityEntry, actorBadge, formatActivity, formatActor } from "./activity";

function translators(locale: Locale) {
  const messages = CATALOGS[locale];
  return {
    t: createTranslator({ locale, messages, namespace: "activity" }),
    statusName: createTranslator({ locale, messages, namespace: "lifecycle.status" }),
    jobField: createTranslator({ locale, messages, namespace: "job" }),
    stageName: createTranslator({ locale, messages, namespace: "pipeline.stage" }),
    sourceName: createTranslator({ locale, messages, namespace: "pipeline.source" }),
  };
}

function render(entry: ActivityEntry, locale: Locale): string {
  return formatActivity(entry, translators(locale));
}

const USER_ACTOR = { id: "00000000-0000-0000-0000-000000000001", full_name: "Nguyễn Văn An" };

function makeEntry(
  action: ActivityEntry["action"],
  overrides: Partial<ActivityEntry> = {},
): ActivityEntry {
  return {
    id: "00000000-0000-0000-0000-000000000099",
    action,
    actor_type: "USER",
    actor: USER_ACTOR,
    before: null,
    after: null,
    created_at: "2026-11-16T06:00:00Z",
    ...overrides,
  };
}

test("formats all four actor types and their badges in vi and en", () => {
  const vi = translators("vi").t;
  const en = translators("en").t;

  expect(formatActor({ actor_type: "USER", actor: USER_ACTOR }, vi)).toBe("Nguyễn Văn An");
  expect(formatActor({ actor_type: "USER", actor: USER_ACTOR }, en)).toBe("Nguyễn Văn An");
  expect(actorBadge("USER", vi)).toBeNull();
  expect(actorBadge("USER", en)).toBeNull();

  expect(formatActor({ actor_type: "SYSTEM", actor: null }, vi)).toBe("Hệ thống");
  expect(formatActor({ actor_type: "SYSTEM", actor: null }, en)).toBe("System");
  expect(actorBadge("SYSTEM", vi)).toBe("Hệ thống");
  expect(actorBadge("SYSTEM", en)).toBe("System");

  expect(formatActor({ actor_type: "PUBLIC", actor: null }, vi)).toBe("Ứng viên (Public Apply)");
  expect(formatActor({ actor_type: "PUBLIC", actor: null }, en)).toBe("Candidate (Public Apply)");
  expect(actorBadge("PUBLIC", vi)).toBe("Public Apply");
  expect(actorBadge("PUBLIC", en)).toBe("Public Apply");

  expect(formatActor({ actor_type: "AGENT", actor: USER_ACTOR }, vi)).toBe("Agent (Nguyễn Văn An)");
  expect(formatActor({ actor_type: "AGENT", actor: USER_ACTOR }, en)).toBe("Agent (Nguyễn Văn An)");
  expect(actorBadge("AGENT", vi)).toBe("Agent");
  expect(actorBadge("AGENT", en)).toBe("Agent");

  expect(render(makeEntry("job.created", { actor_type: "USER", actor: USER_ACTOR }), "vi")).toBe(
    "Nguyễn Văn An đã tạo Job.",
  );
  expect(render(makeEntry("job.created", { actor_type: "AGENT", actor: USER_ACTOR }), "en")).toBe(
    "Agent (Nguyễn Văn An) created the Job.",
  );
  expect(render(makeEntry("job.created", { actor_type: "SYSTEM", actor: null }), "vi")).toBe(
    "Hệ thống đã tạo Job.",
  );
  expect(render(makeEntry("job.created", { actor_type: "PUBLIC", actor: null }), "en")).toBe(
    "Candidate (Public Apply) created the Job.",
  );
});

test("formats all eight Job actions in Vietnamese and English", () => {
  const created = makeEntry("job.created", { after: { status: "DRAFT" } });
  expect(render(created, "vi")).toBe("Nguyễn Văn An đã tạo Job.");
  expect(render(created, "en")).toBe("Nguyễn Văn An created the Job.");

  const parsedOk = makeEntry("job.parsed", {
    actor_type: "SYSTEM",
    actor: null,
    before: { parse_status: "PENDING" },
    after: { parse_status: "SUCCEEDED", parse_error: null },
  });
  expect(render(parsedOk, "vi")).toBe("Hệ thống đã phân tích xong JD.");
  expect(render(parsedOk, "en")).toBe("System parsed the JD.");

  const parsedFailed = makeEntry("job.parsed", {
    actor_type: "SYSTEM",
    actor: null,
    before: { parse_status: "PENDING" },
    after: { parse_status: "FAILED", parse_error: "STUCK" },
  });
  expect(render(parsedFailed, "vi")).toBe("Hệ thống phân tích JD thất bại (STUCK).");
  expect(render(parsedFailed, "en")).toBe("System failed to parse the JD (STUCK).");

  const retried = makeEntry("job.parse_retried");
  expect(render(retried, "vi")).toBe("Nguyễn Văn An đã chạy lại phân tích JD.");
  expect(render(retried, "en")).toBe("Nguyễn Văn An retried parsing the JD.");

  const confirmed = makeEntry("job.criteria_confirmed", {
    after: { weights: { technical: 60, soft_skills: 10, experience: 30 } },
  });
  expect(render(confirmed, "vi")).toBe(
    "Nguyễn Văn An đã xác nhận criteria (Technical 60%, Soft Skills 10%, Experience 30%).",
  );
  expect(render(confirmed, "en")).toBe(
    "Nguyễn Văn An confirmed the criteria (Technical 60%, Soft Skills 10%, Experience 30%).",
  );

  const metadata = makeEntry("job.metadata_changed", {
    before: { location: null, apply_deadline: null },
    after: { location: "Hà Nội", apply_deadline: "2026-12-31" },
  });
  expect(render(metadata, "vi")).toBe(
    "Nguyễn Văn An đã cập nhật thông tin Job (Địa điểm, Hạn nộp hồ sơ).",
  );
  expect(render(metadata, "en")).toBe(
    "Nguyễn Văn An updated the Job details (Location, Application deadline).",
  );

  const statusChanged = makeEntry("job.status_changed", {
    before: { status: "DRAFT" },
    after: { status: "PUBLISHED", action: "publish" },
  });
  expect(render(statusChanged, "vi")).toBe(
    "Nguyễn Văn An đã chuyển trạng thái Job từ Nháp sang Đang tuyển.",
  );
  expect(render(statusChanged, "en")).toBe(
    "Nguyễn Văn An changed the Job status from Draft to Published.",
  );

  const publicOn = makeEntry("job.public_apply_changed", {
    before: { public_apply_enabled: false },
    after: { public_apply_enabled: true },
  });
  expect(render(publicOn, "vi")).toBe("Nguyễn Văn An đã bật Public Apply Link.");
  expect(render(publicOn, "en")).toBe("Nguyễn Văn An enabled the Public Apply Link.");

  const publicOff = makeEntry("job.public_apply_changed", {
    before: { public_apply_enabled: true },
    after: { public_apply_enabled: false },
  });
  expect(render(publicOff, "vi")).toBe("Nguyễn Văn An đã tắt Public Apply Link.");
  expect(render(publicOff, "en")).toBe("Nguyễn Văn An disabled the Public Apply Link.");

  const reviewers = makeEntry("job.reviewers_changed", {
    before: { user_ids: [] },
    after: { user_ids: ["u1", "u2"] },
  });
  expect(render(reviewers, "vi")).toBe("Nguyễn Văn An đã cập nhật danh sách Reviewer (2 người).");
  expect(render(reviewers, "en")).toBe("Nguyễn Văn An updated the Reviewers (2 Reviewers).");
});

test("formats CV upload, CV retry, and Application actions in Vietnamese and English", () => {
  const oneCv = makeEntry("job.cvs_uploaded", {
    after: { upload_batch_id: "b1", file_count: 1 },
  });
  expect(render(oneCv, "vi")).toBe("Nguyễn Văn An đã tải lên 1 CV.");
  expect(render(oneCv, "en")).toBe("Nguyễn Văn An uploaded 1 CV.");

  const threeCvs = makeEntry("job.cvs_uploaded", {
    after: { upload_batch_id: "b2", file_count: 3 },
  });
  expect(render(threeCvs, "vi")).toBe("Nguyễn Văn An đã tải lên 3 CV.");
  expect(render(threeCvs, "en")).toBe("Nguyễn Văn An uploaded 3 CVs.");

  const cvRetried = makeEntry("job.cv_parse_retried", {
    before: { status: "FAILED", error_code: "LLM_UNAVAILABLE" },
    after: { upload_batch_id: "b1", item_id: "i1", status: "PENDING", error_code: null },
  });
  expect(render(cvRetried, "vi")).toBe("Nguyễn Văn An đã chạy lại phân tích CV.");
  expect(render(cvRetried, "en")).toBe("Nguyễn Văn An retried parsing a CV.");

  const appUploaded = makeEntry("application.created", {
    after: {
      source: "UPLOAD",
      candidate_id: "c1",
      cv_document_id: "cv1",
      stage: "APPLIED",
    },
  });
  expect(render(appUploaded, "vi")).toBe(
    "Nguyễn Văn An đã tạo Application (Tải lên, Stage Applied).",
  );
  expect(render(appUploaded, "en")).toBe(
    "Nguyễn Văn An created the Application (Upload, Stage Applied).",
  );

  const appPublic = makeEntry("application.created", {
    actor_type: "PUBLIC",
    actor: null,
    after: {
      source: "PUBLIC_APPLY",
      candidate_id: "c2",
      cv_document_id: "cv2",
      stage: "APPLIED",
    },
  });
  expect(render(appPublic, "vi")).toBe(
    "Ứng viên (Public Apply) đã tạo Application (Public Apply, Stage Applied).",
  );
  expect(render(appPublic, "en")).toBe(
    "Candidate (Public Apply) created the Application (Public Apply, Stage Applied).",
  );

  const stageChanged = makeEntry("application.stage_changed", {
    before: { stage: "APPLIED" },
    after: { stage: "SCREENING" },
  });
  expect(render(stageChanged, "vi")).toBe(
    "Nguyễn Văn An đã chuyển Application từ Applied sang Screening.",
  );
  expect(render(stageChanged, "en")).toBe(
    "Nguyễn Văn An moved the Application from Applied to Screening.",
  );
});
