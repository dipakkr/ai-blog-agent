const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type JobStatus =
  | "pending"
  | "researching"
  | "outlining"
  | "drafting"
  | "scoring"
  | "revising"
  | "completed"
  | "failed";

export interface SeoCheck {
  check: string;
  passed: boolean;
  points_earned: number;
  points_possible: number;
  detail: string;
}

export interface SeoScore {
  total: number;
  passed: boolean;
  checks: SeoCheck[];
}

export interface Section {
  heading: string;
  level: "h2" | "h3";
  content: string;
  word_count: number;
}

export interface InternalLink {
  anchor_text: string;
  suggested_url: string;
  domain?: string;
  context: string;
}

export interface ExternalLink {
  anchor_text: string;
  url: string;
  domain: string;
  context: string;
}

export interface FaqItem {
  question: string;
  answer: string;
}

export interface ArticleResult {
  metadata: {
    title: string;
    meta_description: string;
    primary_keyword: string;
    secondary_keywords: string[];
    slug: string;
  };
  sections: Section[];
  links: {
    internal: InternalLink[];
    external: ExternalLink[];
  };
  faq: FaqItem[];
  word_count: number;
  seo_score: SeoScore;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  topic: string;
  primary_keyword: string;
  target_word_count: number;
  language: string;
  created_at: string;
  updated_at: string;
  error?: string;
  result?: ArticleResult;
}

export interface GenerateRequest {
  topic: string;
  primary_keyword: string;
  target_word_count: number;
  language?: string;
}

export interface GenerateResponse {
  job_id: string;
  status: string;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function generateArticle(body: GenerateRequest): Promise<GenerateResponse> {
  return apiFetch<GenerateResponse>("/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listJobs(): Promise<Job[]> {
  return apiFetch<Job[]>("/jobs");
}

export async function getJob(jobId: string): Promise<Job> {
  return apiFetch<Job>(`/jobs/${jobId}`);
}

export async function retryJob(jobId: string): Promise<GenerateResponse> {
  return apiFetch<GenerateResponse>(`/jobs/${jobId}/retry`, { method: "POST" });
}

// Pipeline data types

export interface SerpResult {
  position: number;
  title: string;
  url: string;
  domain: string;
  snippet: string;
}

export interface SerpTheme {
  theme: string;
  frequency: number;
  sources: string[];
}

export interface SerpData {
  query: string;
  results: SerpResult[];
  people_also_ask: string[];
  themes: SerpTheme[];
}

export interface ClassificationData {
  format: "tutorial" | "comparison" | "listicle" | "explainer" | "case_study";
  audience: "developer" | "business" | "beginner" | "general";
  tone: "technical" | "conversational" | "authoritative" | "beginner_friendly";
  required_elements: string[];
  rationale: string;
}

export interface GapItem {
  topic: string;
  reason: string;
  priority: "high" | "medium" | "low";
}

export interface OutlineSubsection {
  heading: string;
  level: string;
  key_points: string[];
  subsections: OutlineSubsection[];
}

export interface OutlineSection {
  heading: string;
  level: string;
  key_points: string[];
  subsections: OutlineSubsection[];
}

export interface OutlineData {
  title: string;
  meta_description: string;
  secondary_keywords: string[];
  sections: OutlineSection[];
}

export interface DraftSection {
  heading: string;
  level: string;
  word_count: number;
  content: string;
}

export interface DraftData {
  total_words: number;
  content_format: string;
  sections: DraftSection[];
}

export interface PipelineData {
  serp?: SerpData;
  classification?: ClassificationData;
  gaps?: GapItem[];
  outline?: OutlineData;
  draft?: DraftData;
}

export async function getPipelineData(jobId: string): Promise<PipelineData> {
  return apiFetch<PipelineData>(`/jobs/${jobId}/pipeline`);
}

export interface AttemptRecord {
  attempt: number;
  timestamp: string;
  status: string;
  error?: string;
  result?: ArticleResult;
}

export async function getJobHistory(jobId: string): Promise<AttemptRecord[]> {
  return apiFetch<AttemptRecord[]>(`/jobs/${jobId}/history`);
}
