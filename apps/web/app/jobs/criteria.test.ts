import { expect, test } from "vitest";

import { type Job, formFromJob, toConfirmation, weightTotal } from "./criteria";

const parsed: Job = {
  id: "job-1",
  title: "Senior Backend Developer",
  level: "SENIOR",
  department: "Engineering",
  location: null,
  work_mode: "HYBRID",
  status: "DRAFT",
  parse_status: "SUCCEEDED",
  parse_error: null,
  criteria: {
    skills: [{ name: "Python", must_have: true }],
    min_years_experience: 3,
    education: null,
    responsibilities: ["Build APIs", "Review code"],
    salary_range: null,
  },
  verification: { education: "NEEDS_REVIEW" },
  weights: { technical: 55, soft_skills: 15, experience: 30 },
  criteria_confirmed_at: null,
};

test("an unedited form confirms the parsed criteria as they are", () => {
  expect(toConfirmation(formFromJob(parsed))).toEqual({
    title: "Senior Backend Developer",
    level: "SENIOR",
    department: "Engineering",
    location: null,
    work_mode: "HYBRID",
    criteria: parsed.criteria,
    weights: { technical: 55, soft_skills: 15, experience: 30 },
  });
});

test("blank inputs become nulls, and blank skills and responsibilities are dropped", () => {
  const form = formFromJob(parsed);
  form.title = "  Backend Developer ";
  form.department = " ";
  form.work_mode = "";
  form.min_years_experience = "";
  form.responsibilities = "Build APIs\n\n  \n Mentor ";
  form.skills = [...form.skills, { name: "  ", must_have: false }];

  expect(toConfirmation(form)).toMatchObject({
    title: "Backend Developer",
    department: null,
    work_mode: null,
    criteria: {
      skills: [{ name: "Python", must_have: true }],
      min_years_experience: null,
      responsibilities: ["Build APIs", "Mentor"],
    },
  });
});

test("a failed parse starts from an empty form", () => {
  const form = formFromJob({ ...parsed, parse_status: "FAILED", criteria: null });

  expect(form.skills).toEqual([]);
  expect(toConfirmation(form).criteria).toEqual({
    skills: [],
    min_years_experience: null,
    education: null,
    responsibilities: [],
    salary_range: null,
  });
});

test("weights total in percent", () => {
  expect(weightTotal({ technical: 60, soft_skills: 10, experience: 31 })).toBe(101);
});
