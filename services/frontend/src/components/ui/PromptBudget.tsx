import { utf8Bytes } from "@/lib/promptBudget";
import { cn } from "@/lib/cn";

const numberFormat = new Intl.NumberFormat("en-US");

/** Size of a prompt against its provider's byte limit, or a plain character count when the
 *  provider has none. */
export function PromptBudget({
  value,
  limit,
  className,
}: {
  value: string;
  limit?: number;
  className?: string;
}) {
  if (limit === undefined) {
    return (
      <div className={cn("text-right text-xs tabular-nums text-fg-subtle", className)}>
        {value.length} chars
      </div>
    );
  }
  const bytes = utf8Bytes(value);
  const tone =
    bytes > limit ? "text-danger" : bytes > limit * 0.9 ? "text-warning" : "text-fg-subtle";
  return (
    <div
      className={cn("text-right text-xs tabular-nums", tone, className)}
      title="Counted in UTF-8 bytes: dashes, curly quotes and accented letters count extra"
    >
      {numberFormat.format(bytes)} / {numberFormat.format(limit)} bytes
      {bytes > limit && " - over the limit"}
    </div>
  );
}
