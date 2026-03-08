"use client";

import { SeoScore } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface SeoScoreTabProps {
  seoScore: SeoScore;
}

export function SeoScoreTab({ seoScore }: SeoScoreTabProps) {
  const { total, passed, checks } = seoScore;
  const scoreColor =
    total >= 80
      ? "text-green-600"
      : total >= 60
      ? "text-yellow-600"
      : "text-red-600";

  const progressColor =
    total >= 80
      ? "bg-green-500"
      : total >= 60
      ? "bg-yellow-500"
      : "bg-red-500";

  return (
    <div className="space-y-6">
      {/* Score gauge */}
      <div className="flex flex-col items-center gap-4 py-6">
        <div className={cn("text-7xl font-bold tabular-nums", scoreColor)}>
          {total}
          <span className="text-3xl text-muted-foreground font-normal">/100</span>
        </div>
        <div className="w-full max-w-sm space-y-2">
          <Progress
            value={total}
            className="h-3"
          />
        </div>
        <Badge
          variant="outline"
          className={
            passed
              ? "bg-green-100 text-green-700 border-green-300 text-sm px-4 py-1"
              : "bg-red-100 text-red-700 border-red-300 text-sm px-4 py-1"
          }
        >
          {passed ? "SEO PASSED" : "SEO NEEDS IMPROVEMENT"}
        </Badge>
      </div>

      {/* Checks list */}
      <div className="space-y-2">
        <h3 className="font-semibold text-sm uppercase tracking-wide text-muted-foreground mb-3">
          SEO Checks
        </h3>
        {checks.map((check, idx) => (
          <div
            key={idx}
            className={cn(
              "flex items-start gap-3 rounded-lg border p-3",
              check.passed
                ? "bg-green-50 border-green-200"
                : "bg-red-50 border-red-200"
            )}
          >
            <div
              className={cn(
                "mt-0.5 flex-shrink-0 h-5 w-5 rounded-full flex items-center justify-center text-xs font-bold",
                check.passed
                  ? "bg-green-500 text-white"
                  : "bg-red-500 text-white"
              )}
            >
              {check.passed ? "✓" : "✗"}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-sm">{check.check}</p>
                <span className="text-xs font-mono text-muted-foreground whitespace-nowrap">
                  {check.points_earned}/{check.points_possible} pts
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{check.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
