"use client";

import { Badge } from "@/components/ui/badge";
import { JobStatus } from "@/lib/api";
import { STATUS_COLORS, STATUS_LABELS } from "@/lib/status";
import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: JobStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-medium capitalize border",
        STATUS_COLORS[status],
        className
      )}
    >
      {STATUS_LABELS[status]}
    </Badge>
  );
}
