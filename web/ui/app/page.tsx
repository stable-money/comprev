import Link from "next/link";
import { FileVideo, Loader2 } from "lucide-react";
import { fetchReports, fetchActiveJobs } from "@/lib/api";
import type { JobStage } from "@/lib/api";
import { formatDuration } from "@/lib/status";
import { StatusBadge } from "@/components/status-badge";
import { MediaKindTag, ProductTag, Tag } from "@/components/notion";
import { HealthBanner } from "@/components/health-banner";
import { UploadDialog } from "@/components/upload-dialog";
import { AutoRefresh } from "@/components/auto-refresh";

export const dynamic = "force-dynamic";

// Human label for an in-flight job's current stage.
const STAGE_LABELS: Record<JobStage, string> = {
  queued: "Queued",
  sampling: "Sampling frames",
  transcribing: "Transcribing",
  evaluating: "Evaluating",
  routing: "Finalizing",
  done: "Done",
  error: "Error",
};

export default async function Home() {
  const [reports, activeJobs] = await Promise.all([
    fetchReports(),
    fetchActiveJobs(),
  ]);

  // A re-run can have an active job for a video that still has an old report on
  // disk — let the live job row win and hide the stale report row.
  const reviewing = new Set(activeJobs.map((j) => j.video_id));
  const visibleReports = reports.filter((r) => !reviewing.has(r.video_id));
  const hasRows = activeJobs.length > 0 || visibleReports.length > 0;

  return (
    <div className="space-y-8">
      {/* Notion-style page header */}
      <header className="space-y-3">
        <div className="text-5xl leading-none">🎬</div>
        <div className="flex items-end justify-between gap-4">
          <div className="space-y-2">
            <h1 className="text-[2.5rem] font-bold leading-tight tracking-tight">
              Reports
            </h1>
            <p className="text-muted-foreground text-base">
              {reports.length} {reports.length === 1 ? "report" : "reports"}
              {activeJobs.length > 0 && ` · ${activeJobs.length} under review`}
            </p>
          </div>
          <UploadDialog />
        </div>
      </header>

      <HealthBanner />

      {/* Keep the listing fresh while reviews are running. */}
      {activeJobs.length > 0 && <AutoRefresh />}

      {!hasRows ? (
        <div className="border-border flex flex-col items-center gap-3 rounded-md border border-dashed p-12 text-center">
          <FileVideo className="text-muted-foreground h-8 w-8" />
          <div>
            <p className="font-medium">No reviews yet</p>
            <p className="text-muted-foreground text-sm">
              Upload a video to run your first compliance review.
            </p>
          </div>
          <UploadDialog />
        </div>
      ) : (
        <div className="border-border overflow-hidden rounded-md border">
          {/* Header row */}
          <div className="text-muted-foreground grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-4 border-b border-[#e9e9e7] bg-[#f7f7f5] px-3 py-2 text-xs font-medium sm:grid-cols-[1fr_5rem_5rem_8rem_5rem_5rem]">
            <span>Video</span>
            <span>Type</span>
            <span>Product</span>
            <span>Status</span>
            <span className="text-right">Checks</span>
            <span className="text-right">Duration</span>
          </div>
          {/* In-flight reviews, newest concerns first */}
          {activeJobs.map((j) => (
            <Link
              key={j.job_id}
              href={`/jobs/${j.job_id}`}
              className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-4 border-b border-[#f1f1ef] px-3 py-2.5 transition-colors last:border-b-0 hover:bg-[#f7f7f5] sm:grid-cols-[1fr_5rem_5rem_8rem_5rem_5rem]"
            >
              <div className="min-w-0">
                <div className="truncate font-medium">{j.video_id}</div>
                <div className="text-muted-foreground text-xs">
                  {STAGE_LABELS[j.stage]}
                </div>
              </div>
              <div className="flex sm:w-20">
                <MediaKindTag kind={j.kind} />
              </div>
              <div className="flex sm:w-20">
                <ProductTag product={j.product} />
              </div>
              <div className="flex sm:w-32">
                <Tag color="blue">
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  Under review
                </Tag>
              </div>
              <span className="text-muted-foreground text-right text-sm sm:w-20">
                —
              </span>
              <span className="text-muted-foreground text-right text-sm sm:w-20">
                —
              </span>
            </Link>
          ))}
          {visibleReports.map((r) => (
            <Link
              key={r.video_id}
              href={`/reports/${encodeURIComponent(r.video_id)}`}
              className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-4 border-b border-[#f1f1ef] px-3 py-2.5 transition-colors last:border-b-0 hover:bg-[#f7f7f5] sm:grid-cols-[1fr_5rem_5rem_8rem_5rem_5rem]"
            >
              <div className="min-w-0">
                <div className="truncate font-medium">{r.video_id}</div>
                {r.needs_human_review && (
                  <div className="text-muted-foreground text-xs">
                    Needs human review
                  </div>
                )}
              </div>
              <div className="flex sm:w-20">
                {r.media_kind ? (
                  <MediaKindTag kind={r.media_kind} />
                ) : (
                  <span className="text-muted-foreground text-sm">—</span>
                )}
              </div>
              <div className="flex sm:w-20">
                <ProductTag product={r.product} />
              </div>
              <div className="flex sm:w-32">
                <StatusBadge status={r.overall_status} />
              </div>
              <span className="text-right text-sm tabular-nums sm:w-20">
                {r.n_checks}
              </span>
              <span className="text-muted-foreground text-right text-sm tabular-nums sm:w-20">
                {formatDuration(r.duration_seconds)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
