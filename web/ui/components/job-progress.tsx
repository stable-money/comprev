"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Check, Loader2, CircleAlert, ArrowLeft } from "lucide-react";
import type { JobStage, JobStatus, MediaKind } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Step = { key: JobStage; label: string };

// Visible steps differ by input kind — image skips transcription, audio skips
// the visual pass.
function stepsFor(kind: MediaKind): Step[] {
  const queued: Step = { key: "queued", label: "Queued" };
  const evaluating: Step = { key: "evaluating", label: "Evaluating checks" };
  const done: Step = { key: "done", label: "Done" };
  if (kind === "image")
    return [queued, { key: "sampling", label: "Reading image & OCR" }, evaluating, done];
  if (kind === "audio")
    return [queued, { key: "transcribing", label: "Transcribing audio" }, evaluating, done];
  return [
    queued,
    { key: "sampling", label: "Sampling frames & OCR" },
    { key: "transcribing", label: "Transcribing audio" },
    evaluating,
    done,
  ];
}

// "routing" is an instant tail of the evaluating step; fold it in.
function currentIndex(steps: Step[], stage: JobStage): number {
  const key: JobStage = stage === "routing" ? "evaluating" : stage;
  const i = steps.findIndex((s) => s.key === key);
  return i === -1 ? 0 : i;
}

export function JobProgress({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<JobStatus | null>(null);
  const redirected = useRef(false);

  useEffect(() => {
    let poll: ReturnType<typeof setInterval> | null = null;

    function handle(s: JobStatus) {
      setStatus(s);
      if (s.stage === "done" && s.report_ready && !redirected.current) {
        redirected.current = true;
        router.replace(`/reports/${encodeURIComponent(s.video_id)}`);
      }
    }

    // Primary: SSE. Fallback: polling (some proxies buffer event streams).
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.addEventListener("stage", (ev) => {
      try {
        handle(JSON.parse((ev as MessageEvent).data));
      } catch {
        /* ignore malformed frame */
      }
    });
    es.onerror = () => {
      es.close();
      if (poll) return;
      poll = setInterval(async () => {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (res.ok) {
          const s: JobStatus = await res.json();
          handle(s);
          if (s.stage === "done" || s.stage === "error") {
            if (poll) clearInterval(poll);
          }
        }
      }, 1500);
    };

    return () => {
      es.close();
      if (poll) clearInterval(poll);
    };
  }, [jobId, router]);

  const stage = status?.stage ?? "queued";
  const steps = stepsFor(status?.kind ?? "video");
  const current = currentIndex(steps, stage);

  if (stage === "error") {
    return (
      <div className="space-y-4">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ArrowLeft className="h-4 w-4" />
          All reports
        </Link>
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>Review failed</AlertTitle>
          <AlertDescription>
            {status?.error ?? "The engine returned an error."}
          </AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => router.push("/")}>
          Back to reports
        </Button>
      </div>
    );
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle className="text-base">
          Reviewing{" "}
          <span className="font-mono">{status?.video_id ?? "…"}</span>
        </CardTitle>
        <p className="text-muted-foreground text-sm">
          This can take a few minutes. You can leave this page open.
        </p>
      </CardHeader>
      <CardContent>
        <ol className="space-y-4">
          {steps.map((step, i) => {
            const done = i < current;
            const active = i === current;
            return (
              <li key={step.key} className="flex items-center gap-3">
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border text-xs",
                    done && "border-emerald-500 bg-emerald-500/15 text-emerald-500",
                    active && "border-primary text-primary",
                    !done && !active && "border-border text-muted-foreground",
                  )}
                >
                  {done ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : active ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    i + 1
                  )}
                </span>
                <span
                  className={cn(
                    "text-sm",
                    active ? "text-foreground font-medium" : "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
