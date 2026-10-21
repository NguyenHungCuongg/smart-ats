// A Job's criteria as the API sends them, and the edit form over them (FR-A1.1).

import type { JobStatus } from "./lifecycle";

export const LEVELS = ["INTERN", "JUNIOR", "MID", "SENIOR", "LEAD", "MANAGER"] as const;
export const WORK_MODES = ["REMOTE", "HYBRID", "ONSITE"] as const;

export type Level = (typeof LEVELS)[number];
export type WorkMode = (typeof WORK_MODES)[number];
export type Skill = { name: string; must_have: boolean };
export type Criteria = {
  skills: Skill[];
  min_years_experience: number | null;
  education: string | null;
  responsibilities: string[];
  salary_range: string | null;
};
/** Whole percent; the three make 100. */
export type Weights = { technical: number; soft_skills: number; experience: number };

export type Job = {
  id: string;
  title: string;
  level: Level;
  department: string | null;
  location: string | null;
  work_mode: WorkMode | null;
  status: JobStatus;
  parse_status: "PENDING" | "SUCCEEDED" | "FAILED";
  parse_error: string | null;
  criteria: Criteria | null;
  /** VERIFIED or NEEDS_REVIEW per parsed field. */
  verification: Record<string, "VERIFIED" | "NEEDS_REVIEW"> | null;
  weights: Weights;
  criteria_confirmed_at: string | null;
  /** YYYY-MM-DD. */
  apply_deadline: string | null;
};

export type Confirmation = Pick<
  Job,
  "title" | "level" | "department" | "location" | "work_mode" | "weights"
> & { criteria: Criteria };

/** Text inputs hold strings: "" is no value. */
export type Form = {
  title: string;
  level: Level;
  department: string;
  location: string;
  work_mode: WorkMode | "";
  skills: Skill[];
  min_years_experience: string;
  education: string;
  /** One per line. */
  responsibilities: string;
  salary_range: string;
  weights: Weights;
};

export function formFromJob(job: Job): Form {
  const criteria = job.criteria;
  return {
    title: job.title,
    level: job.level,
    department: job.department ?? "",
    location: job.location ?? "",
    work_mode: job.work_mode ?? "",
    skills: criteria?.skills ?? [],
    min_years_experience: criteria?.min_years_experience?.toString() ?? "",
    education: criteria?.education ?? "",
    responsibilities: criteria?.responsibilities.join("\n") ?? "",
    salary_range: criteria?.salary_range ?? "",
    weights: job.weights,
  };
}

const orNull = (value: string) => value.trim() || null;

export function toConfirmation(form: Form): Confirmation {
  return {
    title: form.title.trim(),
    level: form.level,
    department: orNull(form.department),
    location: orNull(form.location),
    work_mode: form.work_mode || null,
    criteria: {
      skills: form.skills
        .map((skill) => ({ ...skill, name: skill.name.trim() }))
        .filter((skill) => skill.name),
      min_years_experience: form.min_years_experience.trim()
        ? Number(form.min_years_experience)
        : null,
      education: orNull(form.education),
      responsibilities: form.responsibilities
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      salary_range: orNull(form.salary_range),
    },
    weights: form.weights,
  };
}

export function weightTotal(weights: Weights): number {
  return weights.technical + weights.soft_skills + weights.experience;
}
