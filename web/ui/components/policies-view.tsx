"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight, FileText, Loader2 } from "lucide-react";
import type { Check, PolicyFile } from "@/lib/api";
import { Tag, type TagColor } from "@/components/notion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function prettyId(id: string): string {
  return id.replace(/^mf_/, "").replace(/_/g, " ");
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(1)} KB`;
}

const SURFACE_COLOR: Record<Check["surface"], TagColor> = {
  visual: "blue",
  audio: "orange",
  both: "green",
};

function SurfaceTag({ surface }: { surface: Check["surface"] }) {
  return <Tag color={SURFACE_COLOR[surface]}>{surface}</Tag>;
}

function SeverityTag({ severity }: { severity: Check["severity"] }) {
  return (
    <Tag color={severity === "serious" ? "red" : "gray"}>{severity}</Tag>
  );
}

/** A small uppercase section heading, Notion column-label style. */
function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-muted-foreground mb-1 px-2 text-xs font-semibold tracking-wide uppercase">
      {children}
    </h2>
  );
}

/** Notion "page properties" row: muted label, value on the right. */
function PropertyRow({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 rounded-md px-2 py-1.5 hover:bg-[#f7f7f5]">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd className="text-sm leading-relaxed">{value}</dd>
    </div>
  );
}

export function PoliciesView({
  policyFiles,
  checks,
}: {
  policyFiles: PolicyFile[];
  checks: Check[];
}) {
  // Two independent overlays: the raw source-file viewer and the per-check detail.
  const [openFile, setOpenFile] = useState<PolicyFile | null>(null);
  const [openCheck, setOpenCheck] = useState<Check | null>(null);

  const [source, setSource] = useState<string | null>(null);
  const [loadingSource, setLoadingSource] = useState(false);

  // Open the file overlay and fetch its raw contents. Browser-side, so use the
  // same-origin /api proxy rather than the server base.
  function viewFile(f: PolicyFile) {
    setOpenFile(f);
    setSource(null);
    setLoadingSource(true);
    fetch(`/api/policies/${encodeURIComponent(f.name)}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then(setSource)
      .catch(() => setSource("Could not load this policy file."))
      .finally(() => setLoadingSource(false));
  }

  return (
    <div className="space-y-10">
      {/* Policy source files — Notion file/link blocks */}
      <section>
        <SectionLabel>Source files</SectionLabel>
        <div className="flex flex-col">
          {policyFiles.map((f) => (
            <button
              key={f.name}
              onClick={() => viewFile(f)}
              className="group flex items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-[#f7f7f5]"
            >
              <FileText className="text-muted-foreground h-5 w-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-medium underline decoration-[#e9e9e7] decoration-2 underline-offset-2">
                    {f.name}
                  </span>
                  <span className="text-muted-foreground truncate text-sm">
                    {f.description}
                  </span>
                </div>
                <span className="text-muted-foreground text-xs">
                  {f.n_checks !== null ? `${f.n_checks} checks · ` : ""}
                  {formatBytes(f.size_bytes)}
                </span>
              </div>
              <ChevronRight className="text-muted-foreground h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          ))}
        </div>
      </section>

      {/* Individual checks — Notion inline database/table */}
      <section>
        <SectionLabel>Checks · {checks.length}</SectionLabel>
        <div className="border-border overflow-hidden rounded-md border">
          <div className="text-muted-foreground bg-[#f7f7f5] grid grid-cols-[1fr_auto_auto] gap-3 border-b border-[#e9e9e7] px-3 py-2 text-xs font-medium">
            <span>Name</span>
            <span className="w-16">Surface</span>
            <span className="w-16">Severity</span>
          </div>
          {checks.map((c) => (
            <button
              key={c.id}
              onClick={() => setOpenCheck(c)}
              className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[#f1f1ef] px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[#f7f7f5]"
            >
              <div className="min-w-0">
                <div className="font-medium capitalize">{prettyId(c.id)}</div>
                <div className="text-muted-foreground truncate text-sm">
                  {c.description}
                </div>
              </div>
              <div className="flex w-16 justify-start">
                <SurfaceTag surface={c.surface} />
              </div>
              <div className="flex w-16 justify-start">
                <SeverityTag severity={c.severity} />
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Overlay: raw policy file contents */}
      <Dialog open={openFile !== null} onOpenChange={(o) => !o && setOpenFile(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="text-muted-foreground h-4 w-4" />
              <span className="font-mono text-sm">{openFile?.name}</span>
            </DialogTitle>
            <DialogDescription>{openFile?.title}</DialogDescription>
          </DialogHeader>
          <div className="max-h-[65vh] overflow-auto rounded-md border border-[#e9e9e7] bg-[#f7f7f5] p-4">
            {loadingSource ? (
              <div className="text-muted-foreground flex items-center gap-2 text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
              </div>
            ) : (
              <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {source}
              </pre>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Overlay: a single check's full definition */}
      <Dialog
        open={openCheck !== null}
        onOpenChange={(o) => !o && setOpenCheck(null)}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-xl capitalize">
              {openCheck && prettyId(openCheck.id)}
            </DialogTitle>
            <DialogDescription className="flex items-center gap-2">
              {openCheck && <SurfaceTag surface={openCheck.surface} />}
              {openCheck && <SeverityTag severity={openCheck.severity} />}
              <span className="text-muted-foreground font-mono text-xs">
                {openCheck?.id}
              </span>
            </DialogDescription>
          </DialogHeader>
          {openCheck && (
            <dl className="-mx-2 max-h-[65vh] overflow-auto">
              <PropertyRow label="Description" value={openCheck.description} />
              <PropertyRow label="Method" value={openCheck.method} />
              <PropertyRow label="Applies when" value={openCheck.applies_when} />
              <PropertyRow
                label="Required text"
                value={
                  openCheck.required_text && (
                    <span className="italic">“{openCheck.required_text}”</span>
                  )
                }
              />
              <PropertyRow
                label="Min on-screen"
                value={
                  openCheck.min_on_screen_seconds !== null
                    ? `${openCheck.min_on_screen_seconds}s`
                    : null
                }
              />
              <PropertyRow label="Pass criteria" value={openCheck.pass_criteria} />
              <PropertyRow label="Policy ref" value={openCheck.policy_ref} />
              <PropertyRow label="Notes" value={openCheck.notes} />
            </dl>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
