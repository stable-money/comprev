"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { renameReport } from "@/lib/api";

/**
 * The report title, editable in place. Click the pencil to edit; Save renames
 * every artifact keyed by the id (and navigates to the new URL), Discard
 * reverts. Enter saves, Escape discards.
 */
export function EditableTitle({ videoId }: { videoId: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(videoId);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  function startEdit() {
    setValue(videoId);
    setEditing(true);
  }

  function discard() {
    setValue(videoId);
    setEditing(false);
  }

  async function save() {
    const next = value.trim();
    if (!next || next === videoId) {
      discard();
      return;
    }
    setBusy(true);
    const result = await renameReport(videoId, next);
    if (result.ok && result.video_id) {
      toast.success(`Renamed to “${result.video_id}”`);
      router.replace(`/reports/${encodeURIComponent(result.video_id)}`);
    } else {
      toast.error(result.error ?? "Couldn’t rename this report.");
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  if (!editing) {
    return (
      <div className="group flex flex-1 items-center gap-2">
        <h1 className="text-[2.25rem] leading-tight font-bold tracking-tight">
          {videoId}
        </h1>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={startEdit}
          aria-label="Edit title"
          className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        >
          <Pencil />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-wrap items-center gap-2">
      <Input
        ref={inputRef}
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            save();
          } else if (e.key === "Escape") {
            e.preventDefault();
            discard();
          }
        }}
        className="h-auto flex-1 px-2 py-1 text-[2.25rem] font-bold tracking-tight md:text-[2.25rem]"
      />
      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="default" onClick={save} disabled={busy}>
          <Check />
          Save
        </Button>
        <Button size="sm" variant="outline" onClick={discard} disabled={busy}>
          <X />
          Discard
        </Button>
      </div>
    </div>
  );
}
