import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// Notion-style pastel tag pills. Server-safe so both server and client
// components can use them.
export type TagColor =
  | "gray"
  | "blue"
  | "red"
  | "green"
  | "orange"
  | "yellow"
  | "purple";

const TAG_STYLES: Record<TagColor, string> = {
  gray: "bg-[#e3e2e0] text-[#37352f]",
  blue: "bg-[#d3e5ef] text-[#183347]",
  red: "bg-[#ffe2dd] text-[#5d1715]",
  green: "bg-[#dbeddb] text-[#1c3829]",
  orange: "bg-[#fadec9] text-[#49290a]",
  yellow: "bg-[#fdecc8] text-[#402c1b]",
  purple: "bg-[#e8deee] text-[#412454]",
};

export function Tag({
  color = "gray",
  className,
  children,
}: {
  color?: TagColor;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
        TAG_STYLES[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

// Maps a media kind (video/image/audio) to a labelled, colour-coded tag.
const MEDIA_KIND_TAGS: Record<string, { color: TagColor; label: string }> = {
  video: { color: "blue", label: "Video" },
  image: { color: "green", label: "Image" },
  audio: { color: "orange", label: "Audio" },
};

export function MediaKindTag({
  kind,
  className,
}: {
  kind?: string | null;
  className?: string;
}) {
  const meta = kind ? MEDIA_KIND_TAGS[kind] : undefined;
  if (!meta) return null;
  return (
    <Tag color={meta.color} className={className}>
      {meta.label}
    </Tag>
  );
}

// Maps a product (mutual_funds/bonds) to a labelled, colour-coded tag.
const PRODUCT_TAGS: Record<string, { color: TagColor; label: string }> = {
  mutual_funds: { color: "blue", label: "MF" },
  bonds: { color: "purple", label: "Bonds" },
};

export function ProductTag({
  product,
  className,
}: {
  product?: string | null;
  className?: string;
}) {
  if (!product) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  const meta = PRODUCT_TAGS[product] ?? { color: "gray" as TagColor, label: product };
  return (
    <Tag color={meta.color} className={className}>
      {meta.label}
    </Tag>
  );
}
