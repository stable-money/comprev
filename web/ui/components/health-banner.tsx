"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { Health } from "@/lib/api";

export function HealthBanner() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  if (!health) return null;
  const degraded = !health.anthropic_key_present || !health.ml_extras_present;
  if (!degraded) return null;

  const missing: string[] = [];
  if (!health.anthropic_key_present) missing.push("ANTHROPIC_API_KEY is not set");
  if (!health.ml_extras_present)
    missing.push("ML extras (paddleocr / faster-whisper) are not installed");

  return (
    // Notion-style yellow callout
    <div className="flex gap-3 rounded-md border border-[#f5e0b3] bg-[#fbf3db] p-4 text-[#402c1b]">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#b45309]" />
      <div className="space-y-1 text-sm">
        <p className="font-medium">Real runs are unavailable</p>
        <p>
          {missing.join("; ")}. New uploads will run in <strong>stub mode</strong>{" "}
          (all checks return “uncertain”). Existing reports still open normally.
        </p>
      </div>
    </div>
  );
}
