import { Tag } from "@/components/notion";
import { statusStyle } from "@/lib/status";
import type { CheckStatus, OverallStatus } from "@/lib/api";

export function StatusBadge({
  status,
  className,
}: {
  status: CheckStatus | OverallStatus;
  className?: string;
}) {
  const { label, color } = statusStyle(status);
  return (
    <Tag color={color} className={className}>
      {label}
    </Tag>
  );
}
