"use client";

import { useState } from "react";
import { AttemptRecord } from "@/lib/api";
import { formatDateTime } from "@/lib/time";
import { Badge } from "@/components/ui/badge";
import { ArticleTab } from "@/components/jobs/ArticleTab";

interface Props {
  history: AttemptRecord[];
}

export function HistoryTab({ history }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        No previous attempts. History is saved each time you retry a job.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {[...history].reverse().map((attempt) => {
        const score = attempt.result?.seo_score?.total;
        const isOpen = expanded === attempt.attempt;

        return (
          <div
            key={attempt.attempt}
            className="rounded-lg border bg-card overflow-hidden"
          >
            {/* Header row */}
            <button
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/40 transition-colors text-left"
              onClick={() => setExpanded(isOpen ? null : attempt.attempt)}
            >
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-muted-foreground w-16">
                  #{attempt.attempt}
                </span>
                <Badge
                  variant="outline"
                  className={
                    attempt.status === "completed"
                      ? "border-green-300 text-green-700"
                      : "border-red-300 text-red-700"
                  }
                >
                  {attempt.status}
                </Badge>
                {score !== undefined && (
                  <span
                    className={`text-sm font-semibold ${
                      score >= 75 ? "text-green-600" : "text-orange-500"
                    }`}
                  >
                    Score: {Math.round(score)}/100
                  </span>
                )}
                {attempt.error && !attempt.result && (
                  <span className="text-xs text-red-600 truncate max-w-xs">
                    {attempt.error}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs text-muted-foreground">
                  {formatDateTime(attempt.timestamp)}
                </span>
                <span className="text-muted-foreground text-sm">
                  {isOpen ? "▲" : "▼"}
                </span>
              </div>
            </button>

            {/* Expanded content */}
            {isOpen && (
              <div className="border-t px-4 py-4 bg-muted/20">
                {attempt.error && (
                  <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-3 py-2">
                    <p className="text-xs text-red-700 font-mono">{attempt.error}</p>
                  </div>
                )}
                {attempt.result ? (
                  <ArticleTab result={attempt.result} />
                ) : (
                  <p className="text-sm text-muted-foreground italic">
                    No article content saved for this attempt.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
