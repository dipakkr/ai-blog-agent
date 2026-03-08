import { JobStatus } from "./api";

export const STATUS_LABELS: Record<JobStatus, string> = {
  pending: "Pending",
  researching: "Researching",
  outlining: "Outlining",
  drafting: "Drafting",
  scoring: "Scoring",
  revising: "Revising",
  completed: "Completed",
  failed: "Failed",
};

export const STATUS_COLORS: Record<JobStatus, string> = {
  pending: "bg-gray-100 text-gray-700 border-gray-300",
  researching: "bg-blue-100 text-blue-700 border-blue-300",
  outlining: "bg-purple-100 text-purple-700 border-purple-300",
  drafting: "bg-yellow-100 text-yellow-700 border-yellow-300",
  scoring: "bg-orange-100 text-orange-700 border-orange-300",
  revising: "bg-yellow-100 text-yellow-700 border-yellow-300",
  completed: "bg-green-100 text-green-700 border-green-300",
  failed: "bg-red-100 text-red-700 border-red-300",
};

export const PIPELINE_STEPS: { label: string; statuses: JobStatus[] }[] = [
  { label: "SERP Research", statuses: ["researching"] },
  { label: "Gap Analysis", statuses: ["researching"] },
  { label: "Outline", statuses: ["outlining"] },
  { label: "Write Article", statuses: ["drafting"] },
  { label: "Link Strategy", statuses: ["drafting"] },
  { label: "FAQ", statuses: ["drafting"] },
  { label: "SEO Score", statuses: ["scoring"] },
  { label: "Revision", statuses: ["revising"] },
];

export const STATUS_STEP_INDEX: Record<JobStatus, number> = {
  pending: -1,
  researching: 1,
  outlining: 2,
  drafting: 4,
  scoring: 6,
  revising: 7,
  completed: 8,
  failed: -1,
};

export function isActiveJob(status: JobStatus): boolean {
  return !["completed", "failed"].includes(status);
}
