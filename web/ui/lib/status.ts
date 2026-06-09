import type { CheckStatus, OverallStatus } from "@/lib/api";
import type { TagColor } from "@/components/notion";

type StatusKey = CheckStatus | OverallStatus;

// Notion pastel tag color + label per verdict. Green = compliant,
// red = violation, yellow = uncertain / needs human review.
const STATUS_STYLES: Record<StatusKey, { label: string; color: TagColor }> = {
  pass: { label: "Pass", color: "green" },
  fail: { label: "Fail", color: "red" },
  uncertain: { label: "Uncertain", color: "yellow" },
  needs_review: { label: "Needs review", color: "yellow" },
};

export function statusStyle(status: StatusKey) {
  return STATUS_STYLES[status] ?? { label: status, color: "gray" as TagColor };
}

export function formatDuration(seconds: number): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
