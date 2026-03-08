"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArticleResult } from "@/lib/api";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface ArticleTabProps {
  result: ArticleResult;
}

function buildRawMarkdown(result: ArticleResult): string {
  const { metadata, sections } = result;
  const lines: string[] = [];
  lines.push(`# ${metadata.title}`, "");
  lines.push(`**Meta description:** ${metadata.meta_description}`, "");
  lines.push(`**Slug:** \`${metadata.slug}\`  **Keyword:** ${metadata.primary_keyword}`, "");
  if (metadata.secondary_keywords?.length) {
    lines.push(`**Secondary keywords:** ${metadata.secondary_keywords.join(", ")}`, "");
  }
  lines.push("---", "");
  for (const section of sections) {
    const prefix = section.level === "h2" ? "## " : "### ";
    lines.push(`${prefix}${section.heading}`, "");
    lines.push(section.content, "");
  }
  return lines.join("\n");
}

// Explicit component map — no dependency on the typography plugin
const markdownComponents: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  h1: ({ children }) => (
    <h1 className="text-2xl font-bold mt-8 mb-3 text-foreground">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xl font-bold mt-6 mb-2 text-foreground border-b pb-1">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-base font-semibold mt-4 mb-1 text-foreground">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="text-sm text-muted-foreground leading-relaxed mb-3">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc list-outside pl-5 mb-3 space-y-1 text-sm text-muted-foreground">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal list-outside pl-5 mb-3 space-y-1 text-sm text-muted-foreground">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-muted-foreground">{children}</em>
  ),
  code: ({ children, className }) => {
    const isBlock = !!className;
    return isBlock ? (
      <code className="block bg-muted border rounded-md p-3 text-xs font-mono leading-relaxed overflow-x-auto whitespace-pre">
        {children}
      </code>
    ) : (
      <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono text-foreground">{children}</code>
    );
  },
  pre: ({ children }) => (
    <pre className="bg-muted border rounded-lg p-4 overflow-x-auto mb-3 text-xs font-mono leading-relaxed">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-primary/40 pl-4 italic text-muted-foreground mb-3 text-sm">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto mb-4">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-muted">{children}</thead>
  ),
  th: ({ children }) => (
    <th className="border border-border px-3 py-2 text-left font-semibold text-foreground text-xs uppercase tracking-wide">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-3 py-2 text-muted-foreground text-sm">{children}</td>
  ),
  tr: ({ children }) => (
    <tr className="even:bg-muted/30">{children}</tr>
  ),
  hr: () => <hr className="my-4 border-border" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:opacity-80"
    >
      {children}
    </a>
  ),
};

export function ArticleTab({ result }: ArticleTabProps) {
  const [view, setView] = useState<"preview" | "raw">("preview");
  const { metadata, sections } = result;
  const rawMarkdown = buildRawMarkdown(result);

  return (
    <div className="space-y-6">
      {/* Metadata card */}
      <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Title</p>
          <p className="font-semibold text-lg leading-snug">{metadata.title}</p>
        </div>
        <Separator />
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Meta Description</p>
          <p className="text-sm text-muted-foreground">{metadata.meta_description}</p>
        </div>
        <Separator />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Slug</p>
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{metadata.slug}</code>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Primary Keyword</p>
            <Badge variant="secondary">{metadata.primary_keyword}</Badge>
          </div>
        </div>
        {metadata.secondary_keywords?.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Secondary Keywords</p>
            <div className="flex flex-wrap gap-1.5">
              {metadata.secondary_keywords.map((kw) => (
                <Badge key={kw} variant="outline" className="text-xs">{kw}</Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Raw / Preview toggle */}
      <div className="flex items-center justify-between border-b pb-3">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Article Content
          <span className="ml-2 normal-case font-normal text-muted-foreground/70">
            {result.word_count.toLocaleString()} words
          </span>
        </p>
        <div className="flex items-center rounded-md border bg-muted/40 p-0.5 gap-0.5">
          <Button
            variant="ghost"
            size="sm"
            className={`h-7 px-3 text-xs rounded-sm transition-colors ${
              view === "preview"
                ? "bg-background shadow-sm text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setView("preview")}
          >
            Preview
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className={`h-7 px-3 text-xs rounded-sm transition-colors ${
              view === "raw"
                ? "bg-background shadow-sm text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setView("raw")}
          >
            Raw
          </Button>
        </div>
      </div>

      {/* Preview — rendered markdown with explicit component styles */}
      {view === "preview" && (
        <div className="space-y-1">
          {sections.map((section, idx) => {
            const HeadingTag = section.level === "h2" ? "h2" : "h3";
            const headingClass =
              section.level === "h2"
                ? "text-xl font-bold mt-6 mb-2 text-foreground border-b pb-1"
                : "text-base font-semibold mt-4 mb-1 text-foreground";
            return (
              <div key={idx}>
                <HeadingTag className={headingClass}>{section.heading}</HeadingTag>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {section.content}
                </ReactMarkdown>
              </div>
            );
          })}
        </div>
      )}

      {/* Raw — plain markdown source with copy button */}
      {view === "raw" && (
        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            className="absolute top-3 right-3 h-7 text-xs z-10"
            onClick={() => navigator.clipboard.writeText(rawMarkdown)}
          >
            Copy
          </Button>
          <pre className="text-xs font-mono leading-relaxed bg-muted/50 border rounded-lg p-4 pr-20 overflow-x-auto whitespace-pre-wrap break-words max-h-[70vh] overflow-y-auto">
            {rawMarkdown}
          </pre>
        </div>
      )}

      <div className="text-right text-sm text-muted-foreground border-t pt-3">
        Total: <span className="font-semibold">{result.word_count.toLocaleString()} words</span>
      </div>
    </div>
  );
}
