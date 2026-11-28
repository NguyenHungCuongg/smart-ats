import type { ActivityEntry } from "./jobs/activity";
import type { Level } from "./jobs/criteria";
import type { JobStatus } from "./jobs/lifecycle";
import type { Stage } from "./jobs/pipeline";

export type ActionJob = {
  id: string;
  title: string;
  level: Level;
  status: JobStatus;
  application_count: number;
};

export type ActionJobGroup = {
  count: number;
  items: ActionJob[];
};

export type ActionItems = {
  pending_criteria_jobs: ActionJobGroup;
  failed_parse_jobs: ActionJobGroup;
  unscored_jobs: ActionJobGroup;
  new_applications_count: number;
};

export type RecentJob = {
  id: string;
  title: string;
  level: Level;
  department: string | null;
  location: string | null;
  status: JobStatus;
  parse_status: "PENDING" | "SUCCEEDED" | "FAILED";
  criteria_confirmed: boolean;
  application_count: number;
  created_at: string;
};

export type DashboardSummary = {
  total_jobs: number;
  jobs_by_status: Record<JobStatus, number>;
  total_applications: number;
  pipeline_by_stage: Record<Stage, number>;
  action_items: ActionItems;
  recent_jobs: RecentJob[];
  recent_activity: ActivityEntry[];
};
