"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { generateArticle, GenerateRequest } from "@/lib/api";

interface NewJobDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (jobId: string) => void;
}

export function NewJobDialog({ open, onOpenChange, onSuccess }: NewJobDialogProps) {
  const [form, setForm] = useState<GenerateRequest>({
    topic: "",
    primary_keyword: "",
    target_word_count: 1500,
    language: "English",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleChange(field: keyof GenerateRequest, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!form.topic.trim()) {
      setError("Topic is required.");
      return;
    }
    if (!form.primary_keyword.trim()) {
      setError("Primary keyword is required.");
      return;
    }

    setLoading(true);
    try {
      const res = await generateArticle(form);
      onSuccess(res.job_id);
      onOpenChange(false);
      setForm({ topic: "", primary_keyword: "", target_word_count: 1500, language: "English" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New Article</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="topic">Topic <span className="text-red-500">*</span></Label>
            <Input
              id="topic"
              placeholder="e.g. Best practices for remote work"
              value={form.topic}
              onChange={(e) => handleChange("topic", e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="keyword">Primary Keyword <span className="text-red-500">*</span></Label>
            <Input
              id="keyword"
              placeholder="e.g. remote work tips"
              value={form.primary_keyword}
              onChange={(e) => handleChange("primary_keyword", e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="wordcount">Target Word Count</Label>
              <Input
                id="wordcount"
                type="number"
                min={300}
                max={10000}
                step={100}
                value={form.target_word_count}
                onChange={(e) => handleChange("target_word_count", parseInt(e.target.value, 10) || 1500)}
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="language">Language</Label>
              <Input
                id="language"
                placeholder="English"
                value={form.language}
                onChange={(e) => handleChange("language", e.target.value)}
                disabled={loading}
              />
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {error}
            </p>
          )}

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Generating..." : "Generate Article"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
