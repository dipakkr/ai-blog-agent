"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Job, listJobs, retryJob } from "@/lib/api";
import { isActiveJob } from "@/lib/status";
import { NewJobDialog } from "@/components/jobs/NewJobDialog";
import { JobsTable } from "@/components/jobs/JobsTable";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      // Sort newest first
      data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setJobs(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Auto-refresh when any job is active
  useEffect(() => {
    const hasActive = jobs.some((j) => isActiveJob(j.status));
    if (hasActive) {
      intervalRef.current = setInterval(fetchJobs, 5000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobs, fetchJobs]);

  async function handleRetry(jobId: string) {
    setRetryingIds((prev) => new Set([...prev, jobId]));
    try {
      await retryJob(jobId);
      await fetchJobs();
    } catch (err) {
      console.error("Retry failed:", err);
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }
  }

  function handleJobCreated() {
    fetchJobs();
  }

  const activeCount = jobs.filter((j) => isActiveJob(j.status)).length;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-bold">
                AI
              </div>
              <div>
                <h1 className="text-lg font-semibold leading-none">AI SEO Content Generator</h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Automated SEO article pipeline
                </p>
              </div>
            </div>
            <Button onClick={() => setDialogOpen(true)}>
              + New Article
            </Button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl py-8">
        {/* Stats bar */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-6">
            <div>
              <span className="text-2xl font-bold">{jobs.length}</span>
              <span className="text-muted-foreground text-sm ml-2">total articles</span>
            </div>
            {activeCount > 0 && (
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                </span>
                <span className="text-sm text-blue-600 font-medium">
                  {activeCount} in progress
                </span>
              </div>
            )}
          </div>
          {activeCount > 0 && (
            <span className="text-xs text-muted-foreground">Auto-refreshing every 5s</span>
          )}
        </div>

        {/* Error state */}
        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}{" "}
            <button
              className="underline font-medium"
              onClick={() => { setLoading(true); fetchJobs(); }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Loading state */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"></div>
              <p className="text-sm text-muted-foreground">Loading jobs...</p>
            </div>
          </div>
        ) : (
          <JobsTable
            jobs={jobs}
            onRetry={handleRetry}
            retryingIds={retryingIds}
          />
        )}
      </main>

      <NewJobDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSuccess={handleJobCreated}
      />
    </div>
  );
}
