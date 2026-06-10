import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Download, Info } from "lucide-react";
import { fetchReport, fetchPolicyFiles } from "@/lib/api";
import type { CheckResult, Evidence, VideoReport } from "@/lib/api";
import { formatDuration } from "@/lib/status";
import { StatusBadge } from "@/components/status-badge";
import { Tag, MediaKindTag } from "@/components/notion";
import { EditableTitle } from "@/components/editable-title";
import { CopyUrlButton } from "@/components/copy-url-button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

export const dynamic = "force-dynamic";

function prettyId(id: string): string {
  return id.replace(/^mf_/, "").replace(/_/g, " ");
}

function evidenceLocation(e: Evidence): string {
  if (e.timestamp) return e.timestamp;
  if (e.frame_index !== null) return `frame ${e.frame_index}`;
  return "—";
}

function EvidenceRow({ e }: { e: Evidence }) {
  const conf: string[] = [];
  if (e.ocr_confidence !== null) conf.push(`ocr ${e.ocr_confidence.toFixed(2)}`);
  if (e.asr_confidence !== null) conf.push(`asr ${e.asr_confidence.toFixed(2)}`);
  return (
    <li className="rounded-md border border-[#e9e9e7] bg-[#f7f7f5] p-3 text-sm">
      <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
        <Tag color={e.surface === "audio" ? "orange" : "blue"}>{e.surface}</Tag>
        <span className="font-mono">{evidenceLocation(e)}</span>
        {conf.length > 0 && <span>· {conf.join(" · ")}</span>}
      </div>
      <p className="italic">“{e.quote}”</p>
    </li>
  );
}

function MediaPreview({
  videoId,
  kind,
}: {
  videoId: string;
  kind: NonNullable<VideoReport["media_kind"]>;
}) {
  // Browser-loaded, so use the same-origin /api proxy (not the server base).
  const src = `/api/reports/${encodeURIComponent(videoId)}/media`;
  return (
    <div className="overflow-hidden rounded-md border border-[#e9e9e7] p-2">
      {kind === "video" && (
        <video
          controls
          preload="metadata"
          className="max-h-[60vh] w-full rounded bg-black"
          src={src}
        />
      )}
      {kind === "image" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt={`Reviewed still for ${videoId}`}
          className="max-h-[60vh] w-full rounded object-contain"
          src={src}
        />
      )}
      {kind === "audio" && (
        <audio controls preload="metadata" className="w-full" src={src} />
      )}
    </div>
  );
}

function CheckItem({ check }: { check: CheckResult }) {
  return (
    <AccordionItem
      value={check.check_id}
      className="border-[#f1f1ef] not-last:border-b"
    >
      <AccordionTrigger className="my-1 px-2 py-4 hover:bg-[#f7f7f5] hover:no-underline">
        <div className="flex flex-1 items-center justify-between gap-3 pr-2">
          <span className="text-left font-medium capitalize">
            {prettyId(check.check_id)}
          </span>
          <div className="flex items-center gap-2">
            {/* n/a checks carry a 'pass' status internally; show a neutral N/A
                badge so they don't read as green passes. */}
            {check.not_applicable ? (
              <Tag color="gray">N/A</Tag>
            ) : (
              <>
                {check.severity === "serious" && <Tag color="red">serious</Tag>}
                <StatusBadge status={check.status} />
              </>
            )}
          </div>
        </div>
      </AccordionTrigger>
      <AccordionContent className="space-y-3 px-2">
        {/* Plain-language verdict + decisive-first findings. Falls back to the
            full prose reasoning for reports generated before structured output. */}
        {check.summary ? (
          <p className="text-sm font-medium leading-relaxed">{check.summary}</p>
        ) : (
          <p className="text-sm leading-relaxed">{check.reasoning}</p>
        )}
        {check.findings && check.findings.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
            {check.findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}
        <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>Confidence: {check.confidence.toFixed(2)}</span>
          <span>Surfaces: {check.surfaces_evaluated.join(", ") || "—"}</span>
          {check.low_confidence_inputs && (
            <span className="text-[#b45309]">Low-confidence inputs</span>
          )}
        </div>
        {check.evidence.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
              Evidence
            </p>
            <ul className="space-y-2">
              {check.evidence.map((e, i) => (
                <EvidenceRow key={i} e={e} />
              ))}
            </ul>
          </div>
        )}
        <p className="text-muted-foreground text-xs">Policy: {check.policy_ref}</p>
      </AccordionContent>
    </AccordionItem>
  );
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ videoId: string }>;
}) {
  const { videoId } = await params;
  const [report, policies] = await Promise.all([
    fetchReport(decodeURIComponent(videoId)),
    fetchPolicyFiles(),
  ]);
  if (!report) notFound();

  // The engine reviews against the check-library policy (the policy file that
  // parses into discrete checks). Surface which one was used.
  const policy = policies.find((p) => p.n_checks != null);

  const tally = { pass: 0, fail: 0, uncertain: 0 };
  for (const c of report.checks) {
    if (!c.not_applicable) tally[c.status] += 1;
  }

  // Show checks grouped by status — pass on top, then fail, then uncertain;
  // not-applicable (excluded from scoring) sink to the bottom. Stable within a
  // group, so the original check-library order is preserved among ties.
  const STATUS_ORDER: Record<string, number> = { pass: 0, fail: 1, uncertain: 2 };
  const sortedChecks = [...report.checks].sort((a, b) => {
    if (a.not_applicable !== b.not_applicable) return a.not_applicable ? 1 : -1;
    return (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3);
  });

  return (
    <div className="space-y-8">
      <Link
        href="/"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="h-4 w-4" />
        All reports
      </Link>

      {/* Notion-style page header */}
      <header className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <EditableTitle videoId={report.video_id} />
          <div className="mt-2 flex shrink-0 items-center gap-2">
            <CopyUrlButton />
            <StatusBadge status={report.overall_status} className="text-sm" />
          </div>
        </div>
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <MediaKindTag kind={report.media_kind} />
          {report.media_kind && <span>·</span>}
          <span>
            {report.product} · {formatDuration(report.duration_seconds)} ·{" "}
            {tally.pass} pass · {tally.fail} fail · {tally.uncertain} uncertain
          </span>
        </div>
        {(report.policy_version || policy) && (
          <div className="text-muted-foreground text-sm">
            Checked against{" "}
            {/* The stamped policy is what actually judged THIS report; fall back
                to the active check-library title for older, unstamped reports.
                Link downloads the authoritative source policy doc for audit. */}
            <a
              href="/api/policy-doc"
              className="hover:text-foreground font-medium underline underline-offset-2"
            >
              {report.policy_version
                ? `${report.product} — ${report.policy_version}`
                : policy?.title}
            </a>
            {report.checks_hash && (
              <span className="font-mono text-xs"> · checks {report.checks_hash}</span>
            )}
          </div>
        )}
      </header>

      {report.review_reasons.length > 0 && (
        // Notion callout block
        <div className="rounded-md border border-[#e9e9e7] bg-[#f7f7f5] p-4">
          <div className="flex gap-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-[#b45309]" />
            <div className="space-y-2">
              <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Review reasons
              </p>
              <ul className="list-inside list-disc space-y-1 text-sm">
                {report.review_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
              <a
                href={`/api/reports/${encodeURIComponent(report.video_id)}/markdown`}
                download={`${report.video_id}.md`}
                className="text-muted-foreground hover:text-foreground mt-1 inline-flex items-center gap-1 text-sm"
              >
                <Download className="h-4 w-4" />
                Download markdown
              </a>
            </div>
          </div>
        </div>
      )}

      {report.media_kind && (
        <MediaPreview videoId={report.video_id} kind={report.media_kind} />
      )}

      <section>
        <h2 className="text-muted-foreground mb-1 px-2 text-xs font-semibold tracking-wide uppercase">
          Checks · {report.checks.length}
        </h2>
        <div className="border-border overflow-hidden rounded-md border px-1">
          <Accordion className="w-full">
            {sortedChecks.map((c) => (
              <CheckItem key={c.check_id} check={c} />
            ))}
          </Accordion>
        </div>
      </section>
    </div>
  );
}
