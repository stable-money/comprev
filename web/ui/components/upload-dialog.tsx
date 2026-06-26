"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Upload,
  Loader2,
  Video,
  ImageIcon,
  AudioLines,
  ArrowLeft,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { PRODUCTS } from "@/lib/api";
import type { Health, MediaKind, Product } from "@/lib/api";

const KINDS: {
  kind: MediaKind;
  label: string;
  hint: string;
  accept: string;
  icon: typeof Video;
}[] = [
  {
    kind: "video",
    label: "Video",
    hint: "Frames + OCR and audio transcription",
    accept: ".mp4,.mov,.mkv,.webm",
    icon: Video,
  },
  {
    kind: "image",
    label: "Image",
    hint: "On-screen text + visual checks",
    accept: ".jpg,.jpeg,.png,.webp,.bmp",
    icon: ImageIcon,
  },
  {
    kind: "audio",
    label: "Audio",
    hint: "Voice-over transcription checks",
    accept: ".mp3,.wav,.m4a,.aac,.ogg,.flac",
    icon: AudioLines,
  },
];

export function UploadDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<MediaKind | null>(null);
  const [product, setProduct] = useState<Product>("mutual_funds");
  const [file, setFile] = useState<File | null>(null);
  const [stub, setStub] = useState(false);
  const [fast, setFast] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);

  // Reset wizard whenever the dialog opens, and default to stub when the
  // backend can't do a real run (no API key / no ML extras).
  useEffect(() => {
    if (!open) return;
    setKind(null);
    setProduct("mutual_funds");
    setFile(null);
    setFast(false);
    setConflict(null);
    setStub(false);
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((h: Health | null) => {
        if (h && (!h.anthropic_key_present || !h.ml_extras_present)) setStub(true);
      })
      .catch(() => {});
  }, [open]);

  const selected = KINDS.find((k) => k.kind === kind);

  async function submit(overwrite: boolean) {
    if (!kind || !file) {
      toast.error("Choose a file first.");
      return;
    }
    setSubmitting(true);
    setConflict(null);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("product", product);
    form.append("stub", String(stub));
    form.append("fast", String(fast));
    form.append("overwrite", String(overwrite));

    try {
      const res = await fetch("/api/jobs", { method: "POST", body: form });
      if (res.status === 409) {
        const data = await res.json();
        setConflict(data.video_id);
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        toast.error(data.detail ?? `Upload failed (${res.status}).`);
        return;
      }
      const { job_id } = await res.json();
      setOpen(false);
      router.push(`/jobs/${job_id}`);
    } catch {
      toast.error("Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button>
            <Upload className="h-4 w-4" />
            Upload
          </Button>
        }
      />
      <DialogContent>
        {/* Step 1 — choose what you're uploading */}
        {!kind && (
          <>
            <DialogHeader>
              <DialogTitle>What are you uploading?</DialogTitle>
              <DialogDescription>
                Pick the input type to review against the compliance checks.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2 py-2">
              {KINDS.map((k) => {
                const Icon = k.icon;
                return (
                  <button
                    key={k.kind}
                    onClick={() => setKind(k.kind)}
                    className="border-border hover:border-primary hover:bg-accent flex items-center gap-3 rounded-md border p-3 text-left transition-colors"
                  >
                    <Icon className="text-muted-foreground h-5 w-5 shrink-0" />
                    <div>
                      <div className="font-medium">{k.label}</div>
                      <div className="text-muted-foreground text-xs">{k.hint}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        )}

        {/* Step 2 — pick the file + options */}
        {kind && selected && (
          <>
            <DialogHeader>
              <button
                onClick={() => {
                  setKind(null);
                  setFile(null);
                  setConflict(null);
                }}
                className="text-muted-foreground hover:text-foreground mb-1 inline-flex items-center gap-1 text-xs"
              >
                <ArrowLeft className="h-3 w-3" />
                Change type
              </button>
              <DialogTitle className="capitalize">Upload {selected.label}</DialogTitle>
              <DialogDescription>{selected.hint}.</DialogDescription>
            </DialogHeader>

            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label>Product</Label>
                <div className="grid grid-cols-2 gap-2">
                  {PRODUCTS.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      onClick={() => setProduct(p.value)}
                      className={cn(
                        "rounded-md border p-2 text-sm transition-colors",
                        product === p.value
                          ? "border-primary bg-accent font-medium"
                          : "border-border text-muted-foreground hover:border-primary hover:bg-accent",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <p className="text-muted-foreground text-xs">
                  Which policy set to review against.
                </p>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="media">{selected.label} file</Label>
                <Input
                  id="media"
                  type="file"
                  accept={selected.accept}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <p className="text-muted-foreground text-xs">
                  {selected.accept.replaceAll(",", " ")} — up to 500 MB.
                </p>
              </div>

              <div className="border-border flex items-center justify-between rounded-md border p-3">
                <div>
                  <Label htmlFor="stub">Stub mode</Label>
                  <p className="text-muted-foreground text-xs">
                    Skip ML + API; every check returns “uncertain”. Fast smoke test.
                  </p>
                </div>
                <Switch id="stub" checked={stub} onCheckedChange={setStub} />
              </div>

              {!stub && (
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={fast} onCheckedChange={(v) => setFast(Boolean(v))} />
                  Fast mode (lower fidelity, quicker)
                </label>
              )}

              {conflict && (
                <div className="border-amber-500/40 bg-amber-500/10 rounded-md border p-3 text-sm">
                  A report for <span className="font-mono">{conflict}</span> already
                  exists.
                  <div className="mt-2 flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setOpen(false);
                        router.push(`/reports/${encodeURIComponent(conflict)}`);
                      }}
                    >
                      View existing
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={submitting}
                      onClick={() => submit(true)}
                    >
                      Re-run (overwrite)
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button onClick={() => submit(false)} disabled={submitting || !file}>
                {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                Start review
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
