"use client";

import { useState } from "react";
import {
  PipelineData,
  SerpData,
  ClassificationData,
  GapItem,
  OutlineData,
  DraftData,
  OutlineSection,
  OutlineSubsection,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface PipelineInspectorProps {
  data: PipelineData;
}

// ──────────────────────────────────────────────
// Helper: stage status badge
// ──────────────────────────────────────────────
function StageStatus({ hasData }: { hasData: boolean }) {
  if (hasData) {
    return (
      <span className="text-green-600 text-base" title="Complete">
        ✅
      </span>
    );
  }
  return (
    <span className="text-muted-foreground text-base" title="Waiting">
      ⏳
    </span>
  );
}

// ──────────────────────────────────────────────
// Helper: collapsible stage card
// ──────────────────────────────────────────────
interface StageCardProps {
  icon: string;
  title: string;
  hasData: boolean;
  children: React.ReactNode;
}

function StageCard({ icon, title, hasData, children }: StageCardProps) {
  const [open, setOpen] = useState(hasData);

  return (
    <Card className={cn("transition-all", !hasData && "opacity-60")}>
      <CardHeader className="py-3 px-4 border-b">
        <button
          className="flex w-full items-center gap-3 text-left"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          <span className="text-xl">{icon}</span>
          <span className="font-semibold text-base flex-1">{title}</span>
          <StageStatus hasData={hasData} />
          <span className="text-muted-foreground text-xs ml-2">
            {open ? "▲" : "▼"}
          </span>
        </button>
      </CardHeader>

      {open && (
        <CardContent className="pt-4">
          {hasData ? (
            children
          ) : (
            <p className="text-sm text-muted-foreground italic py-4 text-center">
              Waiting for this stage to complete…
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// ──────────────────────────────────────────────
// Stage 1: SERP Research
// ──────────────────────────────────────────────
const THEME_COLORS = [
  "bg-blue-100 text-blue-800 border-blue-200",
  "bg-purple-100 text-purple-800 border-purple-200",
  "bg-teal-100 text-teal-800 border-teal-200",
  "bg-orange-100 text-orange-800 border-orange-200",
  "bg-pink-100 text-pink-800 border-pink-200",
  "bg-indigo-100 text-indigo-800 border-indigo-200",
];

function SerpStage({ serp }: { serp: SerpData }) {
  return (
    <div className="space-y-6">
      <div>
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Query
        </span>
        <p className="mt-1 font-medium">{serp.query}</p>
      </div>

      {/* Results table */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Search Results
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Domain</TableHead>
              <TableHead className="hidden md:table-cell">Snippet</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {serp.results.map((r) => (
              <TableRow key={r.position}>
                <TableCell className="text-muted-foreground font-mono text-xs">
                  {r.position}
                </TableCell>
                <TableCell>
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline text-xs font-medium"
                  >
                    {r.title}
                  </a>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {r.domain}
                </TableCell>
                <TableCell className="hidden md:table-cell text-xs text-muted-foreground whitespace-normal max-w-xs">
                  {r.snippet.length > 100
                    ? r.snippet.slice(0, 100) + "…"
                    : r.snippet}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* People Also Ask */}
      {serp.people_also_ask.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            People Also Ask
          </p>
          <ul className="space-y-1.5">
            {serp.people_also_ask.map((q, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="text-muted-foreground mt-0.5">❓</span>
                <span>{q}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Themes */}
      {serp.themes.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Themes Detected
          </p>
          <div className="flex flex-wrap gap-2">
            {serp.themes.map((t, i) => (
              <span
                key={i}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-3 py-0.5 text-xs font-medium",
                  THEME_COLORS[i % THEME_COLORS.length]
                )}
              >
                {t.theme}
                <span className="opacity-70">×{t.frequency}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────
// Stage 2: Content Classification
// ──────────────────────────────────────────────
const FORMAT_LABELS: Record<string, string> = {
  tutorial: "Tutorial",
  comparison: "Comparison",
  listicle: "Listicle",
  explainer: "Explainer",
  case_study: "Case Study",
};

function ClassificationStage({ cls }: { cls: ClassificationData }) {
  return (
    <div className="space-y-5">
      {/* Format badge */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground w-20">
          Format
        </span>
        <Badge className="text-sm px-4 py-1 bg-blue-600 text-white border-0">
          {FORMAT_LABELS[cls.format] ?? cls.format}
        </Badge>
      </div>

      {/* Audience + Tone */}
      <div className="flex flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Audience
          </span>
          <Badge variant="secondary" className="capitalize">
            {cls.audience}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Tone
          </span>
          <Badge variant="secondary" className="capitalize">
            {cls.tone.replace(/_/g, " ")}
          </Badge>
        </div>
      </div>

      {/* Required elements */}
      {cls.required_elements.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Required Elements
          </p>
          <div className="flex flex-wrap gap-1.5">
            {cls.required_elements.map((el, i) => (
              <Badge key={i} variant="outline" className="text-xs capitalize">
                {el}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Rationale */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Rationale
        </p>
        <blockquote className="border-l-4 border-muted pl-3 text-sm text-muted-foreground italic">
          {cls.rationale}
        </blockquote>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Stage 3: Content Gap Analysis
// ──────────────────────────────────────────────
const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-red-100 text-red-700 border-red-200",
  medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
  low: "bg-green-100 text-green-700 border-green-200",
};

function GapsStage({ gaps }: { gaps: GapItem[] }) {
  if (gaps.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">No gaps identified.</p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-24">Priority</TableHead>
          <TableHead>Topic</TableHead>
          <TableHead className="hidden md:table-cell">Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {gaps.map((g, i) => (
          <TableRow key={i}>
            <TableCell>
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
                  PRIORITY_STYLES[g.priority] ?? "bg-muted text-foreground border-muted"
                )}
              >
                {g.priority}
              </span>
            </TableCell>
            <TableCell className="font-medium text-sm whitespace-normal">
              {g.topic}
            </TableCell>
            <TableCell className="hidden md:table-cell text-xs text-muted-foreground whitespace-normal">
              {g.reason}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// ──────────────────────────────────────────────
// Stage 4: Outline
// ──────────────────────────────────────────────
function SubsectionTree({ subsections }: { subsections: OutlineSubsection[] }) {
  if (!subsections || subsections.length === 0) return null;
  return (
    <ul className="ml-5 mt-1 space-y-2 border-l pl-3">
      {subsections.map((sub, i) => (
        <li key={i}>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {sub.level.toUpperCase()} — {sub.heading}
          </p>
          {sub.key_points.length > 0 && (
            <ul className="mt-0.5 space-y-0.5 list-disc list-inside">
              {sub.key_points.map((kp, j) => (
                <li key={j} className="text-xs text-muted-foreground">
                  {kp}
                </li>
              ))}
            </ul>
          )}
          <SubsectionTree subsections={sub.subsections} />
        </li>
      ))}
    </ul>
  );
}

function SectionTree({ sections }: { sections: OutlineSection[] }) {
  return (
    <ul className="space-y-4">
      {sections.map((sec, i) => (
        <li key={i} className="rounded-lg border p-3 bg-muted/20">
          <p className="font-semibold text-sm">
            <span className="text-muted-foreground text-xs mr-2 uppercase">
              {sec.level}
            </span>
            {sec.heading}
          </p>
          {sec.key_points.length > 0 && (
            <ul className="mt-1 space-y-0.5 list-disc list-inside ml-1">
              {sec.key_points.map((kp, j) => (
                <li key={j} className="text-xs text-muted-foreground">
                  {kp}
                </li>
              ))}
            </ul>
          )}
          <SubsectionTree subsections={sec.subsections} />
        </li>
      ))}
    </ul>
  );
}

function OutlineStage({ outline }: { outline: OutlineData }) {
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Title
        </p>
        <p className="font-semibold text-base">{outline.title}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Meta Description
        </p>
        <p className="text-sm text-muted-foreground">{outline.meta_description}</p>
      </div>
      {outline.secondary_keywords.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Secondary Keywords
          </p>
          <div className="flex flex-wrap gap-1.5">
            {outline.secondary_keywords.map((kw, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {kw}
              </Badge>
            ))}
          </div>
        </div>
      )}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Sections
        </p>
        <SectionTree sections={outline.sections} />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Stage 5: Draft
// ──────────────────────────────────────────────
function DraftStage({ draft }: { draft: DraftData }) {
  const [expandedSections, setExpandedSections] = useState<Set<number>>(
    new Set()
  );

  function toggle(idx: number) {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Total Words
        </span>
        <Badge variant="secondary" className="text-sm font-bold px-3">
          {draft.total_words.toLocaleString()}
        </Badge>
        {draft.content_format && (
          <>
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground ml-3">
              Format
            </span>
            <Badge variant="outline" className="text-xs capitalize">
              {draft.content_format}
            </Badge>
          </>
        )}
      </div>

      <div className="space-y-2">
        {draft.sections.map((sec, i) => {
          const isOpen = expandedSections.has(i);
          return (
            <div key={i} className="rounded-lg border bg-muted/10">
              <button
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                onClick={() => toggle(i)}
                aria-expanded={isOpen}
              >
                <span className="text-xs font-mono text-muted-foreground uppercase w-8">
                  {sec.level}
                </span>
                <span className="flex-1 font-medium text-sm">{sec.heading}</span>
                <Badge variant="outline" className="text-xs shrink-0">
                  {sec.word_count} words
                </Badge>
                <span className="text-muted-foreground text-xs ml-1">
                  {isOpen ? "▲" : "▼"}
                </span>
              </button>
              {isOpen && (
                <div className="border-t px-4 py-3">
                  <div className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
                    {sec.content}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Main PipelineInspector
// ──────────────────────────────────────────────
export function PipelineInspector({ data }: PipelineInspectorProps) {
  return (
    <div className="space-y-3">
      {/* Stage 1 */}
      <StageCard
        icon="🔍"
        title="SERP Research"
        hasData={!!data.serp}
      >
        {data.serp && <SerpStage serp={data.serp} />}
      </StageCard>

      {/* Stage 2 */}
      <StageCard
        icon="🏷️"
        title="Content Classification"
        hasData={!!data.classification}
      >
        {data.classification && (
          <ClassificationStage cls={data.classification} />
        )}
      </StageCard>

      {/* Stage 3 */}
      <StageCard
        icon="🕵️"
        title="Content Gap Analysis"
        hasData={!!data.gaps}
      >
        {data.gaps && <GapsStage gaps={data.gaps} />}
      </StageCard>

      {/* Stage 4 */}
      <StageCard
        icon="📋"
        title="Outline"
        hasData={!!data.outline}
      >
        {data.outline && <OutlineStage outline={data.outline} />}
      </StageCard>

      {/* Stage 5 */}
      <StageCard
        icon="✍️"
        title="Draft"
        hasData={!!data.draft}
      >
        {data.draft && <DraftStage draft={data.draft} />}
      </StageCard>
    </div>
  );
}
