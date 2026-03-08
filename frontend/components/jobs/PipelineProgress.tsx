"use client";

import { JobStatus } from "@/lib/api";
import { PIPELINE_STEPS, STATUS_STEP_INDEX } from "@/lib/status";
import { cn } from "@/lib/utils";

interface PipelineProgressProps {
  status: JobStatus;
}

export function PipelineProgress({ status }: PipelineProgressProps) {
  const currentStepIndex = STATUS_STEP_INDEX[status];
  const isCompleted = status === "completed";
  const isFailed = status === "failed";

  return (
    <div className="w-full">
      <div className="flex items-start gap-0">
        {PIPELINE_STEPS.map((step, idx) => {
          const done = isCompleted || (currentStepIndex > idx && !isFailed);
          const active = !isFailed && currentStepIndex === idx + 1;
          const upcoming = !done && !active;

          return (
            <div key={step.label} className="flex-1 flex flex-col items-center">
              {/* Connector line + circle row */}
              <div className="flex items-center w-full">
                {/* Left connector */}
                <div
                  className={cn(
                    "h-0.5 flex-1",
                    idx === 0 ? "opacity-0" : done || active ? "bg-primary" : "bg-border"
                  )}
                />
                {/* Circle */}
                <div
                  className={cn(
                    "flex-shrink-0 h-6 w-6 rounded-full border-2 flex items-center justify-center text-[10px] font-bold transition-all",
                    done
                      ? "bg-primary border-primary text-primary-foreground"
                      : active
                      ? "bg-background border-primary text-primary animate-pulse"
                      : isFailed && currentStepIndex === -1
                      ? "bg-background border-border text-muted-foreground"
                      : "bg-background border-border text-muted-foreground"
                  )}
                >
                  {done ? "✓" : idx + 1}
                </div>
                {/* Right connector */}
                <div
                  className={cn(
                    "h-0.5 flex-1",
                    idx === PIPELINE_STEPS.length - 1
                      ? "opacity-0"
                      : done
                      ? "bg-primary"
                      : "bg-border"
                  )}
                />
              </div>
              {/* Label */}
              <span
                className={cn(
                  "mt-1.5 text-[10px] text-center leading-tight px-0.5",
                  done
                    ? "text-primary font-medium"
                    : active
                    ? "text-primary font-semibold"
                    : "text-muted-foreground"
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
