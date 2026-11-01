import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { ScoreResult } from "../scoring";
import { Result } from "./scoring";

const claim = { text: "Python vững", evidence: [], grounded: true };
const axis = { reason: "theo rubric", evidence: [], grounded: true, grade: 4 };

// Scored by v0: must_have_detail holds names only, and there is no experience_detail.
const v0: ScoreResult = {
  application_id: "app-1",
  full_name: "Nguyễn Văn An",
  status: "SCORED",
  cv_document_id: "cv-1",
  current_cv_document_id: "cv-1",
  technical_score: 80,
  soft_skills_score: 50,
  experience_score: 75,
  total_score: 74,
  must_have_coverage: 0.5,
  must_have_detail: { matched: ["Python"], missing: ["Kubernetes"] },
  experience_detail: null,
  rubric_grades: { technical: axis, soft_skills: axis, experience: axis },
  fit_gap_report: { strengths: [claim], gaps: [claim], recommendations: [claim] },
  error_code: null,
};

const v1: ScoreResult = {
  ...v0,
  must_have_detail: {
    matched: ["Python", "REST API"],
    missing: ["Kubernetes"],
    matches: [
      { must_have: "Python", cv_skill: "python", method: "EXACT", similarity: null },
      {
        must_have: "REST API",
        cv_skill: "RESTful services",
        method: "SEMANTIC",
        similarity: 0.9512,
      },
    ],
  },
  experience_detail: {
    entries: [
      {
        company: "Công ty ABC",
        title: "Backend Developer",
        start: "03/2021",
        end: "nay",
        months: 69,
      },
      { company: "Acme", title: "Intern", start: "2020", end: "2020", months: 12 },
    ],
    total_months: 81,
    unreadable: [{ company: "Beta", title: "Tester", start: null, end: "05/2019", months: null }],
  },
};

const render = (locale: Locale, result: ScoreResult) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <Result result={result} />
    </NextIntlClientProvider>,
  );

test("a v1 Score Result shows the CV skill and method of each match, and the timeline", () => {
  const html = render("en", v1);

  // Skill names, companies and titles as the CV and JD write them, never translated.
  expect(html).toContain("Python: python in the CV (exact)");
  expect(html).toContain("REST API: RESTful services in the CV (by meaning, similarity 0.95)");
  expect(html).toContain("Missing: Kubernetes");
  expect(html).toContain("Experience timeline: 6.8 years in total");
  expect(html).toContain("Backend Developer · Công ty ABC (03/2021 – nay): 69 months");
  expect(html).toContain("Intern · Acme (2020 – 2020): 12 months");
  expect(html).toContain("Couldn&#x27;t count: Tester · Beta (— – 05/2019)");
});

test("in Vietnamese, with numbers in the Vietnamese format", () => {
  const html = render("vi", v1);

  expect(html).toContain("REST API: RESTful services trong CV (theo nghĩa, độ tương đồng 0,95)");
  expect(html).toContain("Python: python trong CV (khớp chính xác)");
  expect(html).toContain("Timeline kinh nghiệm: tổng 6,8 năm");
  expect(html).toContain("Backend Developer · Công ty ABC (03/2021 – nay): 69 tháng");
  expect(html).toContain("Không tính được: Tester · Beta (— – 05/2019)");
});

test("a v0 Score Result still shows its matched and missing names, without a timeline", () => {
  const html = render("en", v0);

  expect(html).toContain("Matched: Python");
  expect(html).toContain("Missing: Kubernetes");
  expect(html).not.toContain("Experience timeline");
  expect(html).not.toContain("in the CV");
});
