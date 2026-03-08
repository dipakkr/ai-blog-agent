"use client";

import { useRouter } from "next/navigation";
import { Job } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDistanceToNow } from "@/lib/time";

interface JobsTableProps {
  jobs: Job[];
  onRetry: (jobId: string) => void;
  retryingIds: Set<string>;
}

export function JobsTable({ jobs, onRetry, retryingIds }: JobsTableProps) {
  const router = useRouter();

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
        <p className="text-lg font-medium">No articles yet</p>
        <p className="text-sm mt-1">Click &quot;New Article&quot; to get started.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead className="font-semibold">Topic</TableHead>
            <TableHead className="font-semibold">Keyword</TableHead>
            <TableHead className="font-semibold">Status</TableHead>
            <TableHead className="font-semibold text-right">Words</TableHead>
            <TableHead className="font-semibold">Created</TableHead>
            <TableHead className="font-semibold text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow key={job.job_id} className="hover:bg-muted/30 transition-colors">
              <TableCell className="font-medium max-w-[200px] truncate" title={job.topic}>
                {job.topic}
              </TableCell>
              <TableCell className="text-muted-foreground max-w-[140px] truncate" title={job.primary_keyword}>
                {job.primary_keyword}
              </TableCell>
              <TableCell>
                <StatusBadge status={job.status} />
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                {job.result?.word_count?.toLocaleString() ?? job.target_word_count.toLocaleString()}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {formatDistanceToNow(job.created_at)}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-2">
                  {job.status === "failed" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onRetry(job.job_id)}
                      disabled={retryingIds.has(job.job_id)}
                      className="text-orange-600 border-orange-300 hover:bg-orange-50"
                    >
                      {retryingIds.has(job.job_id) ? "Retrying..." : "Retry"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => router.push(`/jobs/${job.job_id}`)}
                  >
                    View
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
