"use client";

import { useState } from "react";
import { Check, Link2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

/** Copies the current report URL to the clipboard (with brief confirmation). */
export function CopyUrlButton() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      toast.success("Link copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn’t copy the link.");
    }
  }

  return (
    <Button size="sm" variant="outline" onClick={copy} aria-label="Copy link">
      {copied ? <Check /> : <Link2 />}
      {copied ? "Copied" : "Copy link"}
    </Button>
  );
}
