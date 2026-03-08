"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AttemptRecord,
  Job,
  PipelineData,
  getJob,
  getJobHistory,
  getPipelineData,
  retryJob,
} from "@/lib/api";
import { isActiveJob, STATUS_LABELS } from "@/lib/status";
import { StatusBadge } from "@/components/jobs/StatusBadge";
import { PipelineProgress } from "@/components/jobs/PipelineProgress";
import { ArticleTab } from "@/components/jobs/ArticleTab";
import { SeoScoreTab } from "@/components/jobs/SeoScoreTab";
import { LinksTab } from "@/components/jobs/LinksTab";
import { FaqTab } from "@/components/jobs/FaqTab";
import { HistoryTab } from "@/components/jobs/HistoryTab";
import { PipelineInspector } from "@/components/jobs/PipelineInspector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { formatDateTime } from "@/lib/time";

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.id as string;

  const [job, setJob] = useState<Job | null>(null);
  const [pipelineData, setPipelineData] = useState<PipelineData | null>(null);
  const [history, setHistory] = useState<AttemptRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchJob = useCallback(async () => {
    try {
      const data = await getJob(jobId);
      setJob(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job.");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const fetchPipeline = useCallback(async () => {
    try {
      const data = await getPipelineData(jobId);
      setPipelineData(data);
    } catch {
      // Pipeline data may not be available yet; silently ignore
    }
  }, [jobId]);

  const fetchHistory = useCallback(async () => {
    try {
      const data = await getJobHistory(jobId);
      setHistory(data);
    } catch {
      // History is optional; silently ignore
    }
  }, [jobId]);

  useEffect(() => {
    fetchJob();
    fetchPipeline();
    fetchHistory();
  }, [fetchJob, fetchPipeline, fetchHistory]);

  // Auto-refresh when job is in progress
  useEffect(() => {
    if (!job) return;
    if (isActiveJob(job.status)) {
      intervalRef.current = setInterval(() => {
        fetchJob();
        fetchPipeline();
      }, 3000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [job, fetchJob, fetchPipeline]);

  async function handleRetry() {
    if (!job) return;
    setRetrying(true);
    try {
      await retryJob(job.job_id);
      await fetchJob();
      await fetchPipeline();
      await fetchHistory();
    } catch (err) {
      console.error("Retry failed:", err);
    } finally {
      setRetrying(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"></div>
          <p className="text-sm text-muted-foreground">Loading job...</p>
        </div>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-red-600">{error ?? "Job not found."}</p>
          <Button variant="outline" onClick={() => router.push("/")}>
            Back to Dashboard
          </Button>
        </div>
      </div>
    );
  }

  const isActive = isActiveJob(job.status);
  const isFailed = job.status === "failed";
  const isCompleted = job.status === "completed";
  const hasResult = !!job.result;
  const showTabs = (isCompleted || isFailed) && hasResult;

  // Build tab list dynamically based on available data
  const tabCols = [
    "article",
    "seo",
    "links",
    "faq",
    ...(history.length > 0 ? ["history"] : []),
    ...(pipelineData ? ["pipeline"] : []),
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push("/")}
                className="gap-1"
              >
                ← Back
              </Button>
              <Separator orientation="vertical" className="h-5" />
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-bold">
                  AI
                </div>
                <span className="font-medium text-sm hidden sm:block">
                  AI SEO Content Generator
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {isFailed && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRetry}
                  disabled={retrying}
                  className="text-orange-600 border-orange-300 hover:bg-orange-50"
                >
                  {retrying ? "Retrying..." : "Retry Job"}
                </Button>
              )}
              <StatusBadge status={job.status} />
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl py-8 space-y-6">
        {/* Job info card */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle className="text-xl leading-snug">{job.topic}</CardTitle>
                <p className="text-sm text-muted-foreground mt-1">
                  Keyword:{" "}
                  <span className="font-medium text-foreground">
                    {job.primary_keyword}
                  </span>
                  {" · "}
                  Target:{" "}
                  <span className="font-medium text-foreground">
                    {job.target_word_count.toLocaleString()} words
                  </span>
                  {" · "}
                  Language:{" "}
                  <span className="font-medium text-foreground">{job.language}</span>
                </p>
              </div>
              <div className="text-right text-xs text-muted-foreground shrink-0">
                <p>Created: {formatDateTime(job.created_at)}</p>
                <p>Updated: {formatDateTime(job.updated_at)}</p>
                <p className="font-mono mt-1 opacity-60">{job.job_id}</p>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <PipelineProgress status={job.status} />
          </CardContent>
        </Card>

        {/* In-progress state */}
        {isActive && (
          <Card>
            <CardContent className="py-10">
              <div className="flex flex-col items-center gap-4">
                <div className="h-10 w-10 animate-spin rounded-full border-4 border-muted border-t-primary"></div>
                <div className="text-center">
                  <p className="font-semibold text-lg">
                    {STATUS_LABELS[job.status]}...
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Auto-refreshing every 3 seconds
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Failed state — error + retry (shown above article preview) */}
        {isFailed && (
          <Card className="border-red-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-red-700 text-base">Job Failed</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {job.error && (
                <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3">
                  <p className="text-sm text-red-700 font-mono whitespace-pre-wrap">
                    {job.error}
                  </p>
                </div>
              )}
              {hasResult && (
                <p className="text-sm text-muted-foreground">
                  A partial draft was saved — preview it in the tabs below, then retry to improve it.
                </p>
              )}
              <Button
                onClick={handleRetry}
                disabled={retrying}
                variant="outline"
                className="text-orange-600 border-orange-300 hover:bg-orange-50"
              >
                {retrying ? "Retrying..." : "Retry Job"}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Main tabs — shown for completed jobs and failed jobs that have a saved draft */}
        {showTabs && (
          <Card>
            <CardContent className="pt-6">
              <Tabs defaultValue="article">
                <TabsList
                  className="mb-6 w-full"
                  style={{
                    display: "grid",
                    gridTemplateColumns: `repeat(${tabCols.length}, minmax(0, 1fr))`,
                    maxWidth: `${tabCols.length * 120}px`,
                  }}
                >
                  <TabsTrigger value="article">Article</TabsTrigger>
                  <TabsTrigger value="seo">SEO Score</TabsTrigger>
                  <TabsTrigger value="links">Links</TabsTrigger>
                  <TabsTrigger value="faq">FAQ</TabsTrigger>
                  {history.length > 0 && (
                    <TabsTrigger value="history">
                      History{" "}
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({history.length})
                      </span>
                    </TabsTrigger>
                  )}
                  {pipelineData && (
                    <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
                  )}
                </TabsList>

                <TabsContent value="article">
                  <ArticleTab result={job.result!} />
                </TabsContent>

                <TabsContent value="seo">
                  <SeoScoreTab seoScore={job.result!.seo_score} />
                </TabsContent>

                <TabsContent value="links">
                  <LinksTab
                    internal={job.result!.links.internal}
                    external={job.result!.links.external}
                  />
                </TabsContent>

                <TabsContent value="faq">
                  <FaqTab faq={job.result!.faq} />
                </TabsContent>

                {history.length > 0 && (
                  <TabsContent value="history">
                    <HistoryTab history={history} />
                  </TabsContent>
                )}

                {pipelineData && (
                  <TabsContent value="pipeline">
                    <PipelineInspector data={pipelineData} />
                  </TabsContent>
                )}
              </Tabs>
            </CardContent>
          </Card>
        )}

        {/* In-progress: show pipeline inspector only */}
        {isActive && pipelineData && (
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                  Pipeline Inspector
                </span>
                <span className="text-xs text-muted-foreground italic">
                  — updating live
                </span>
              </div>
              <PipelineInspector data={pipelineData} />
            </CardContent>
          </Card>
        )}

        {/* Failed with no draft — show pipeline inspector if available */}
        {isFailed && !hasResult && pipelineData && (
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                  Pipeline Inspector
                </span>
              </div>
              <PipelineInspector data={pipelineData} />
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
