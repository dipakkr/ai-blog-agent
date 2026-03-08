"use client";

import { InternalLink, ExternalLink } from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface LinksTabProps {
  internal: InternalLink[];
  external: ExternalLink[];
}

export function LinksTab({ internal, external }: LinksTabProps) {
  return (
    <div className="space-y-8">
      {/* Internal links */}
      <div>
        <h3 className="font-semibold mb-3">
          Internal Links{" "}
          <span className="text-muted-foreground font-normal text-sm">({internal.length})</span>
        </h3>
        {internal.length === 0 ? (
          <p className="text-sm text-muted-foreground">No internal links suggested.</p>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>Anchor Text</TableHead>
                  <TableHead>Suggested URL</TableHead>
                  <TableHead>Domain</TableHead>
                  <TableHead>Context</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {internal.map((link, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium text-sm">{link.anchor_text}</TableCell>
                    <TableCell className="text-sm">
                      <code className="text-xs bg-muted px-1 py-0.5 rounded">{link.suggested_url}</code>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{link.domain ?? "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate" title={link.context}>
                      {link.context}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* External links */}
      <div>
        <h3 className="font-semibold mb-3">
          External Links{" "}
          <span className="text-muted-foreground font-normal text-sm">({external.length})</span>
        </h3>
        {external.length === 0 ? (
          <p className="text-sm text-muted-foreground">No external links suggested.</p>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>Anchor Text</TableHead>
                  <TableHead>URL</TableHead>
                  <TableHead>Domain</TableHead>
                  <TableHead>Context</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {external.map((link, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium text-sm">{link.anchor_text}</TableCell>
                    <TableCell className="text-sm">
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline text-xs"
                      >
                        {link.url}
                      </a>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{link.domain}</TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate" title={link.context}>
                      {link.context}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
