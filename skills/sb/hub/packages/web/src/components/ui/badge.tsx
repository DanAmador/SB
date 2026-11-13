import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex max-w-full shrink-0 items-center gap-1 truncate rounded-full border px-2 py-px text-xs font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0", {
  variants: {
    tone: {
      neutral: "border-border text-muted-foreground",
      brand: "border-transparent bg-brand-soft text-brand",
      ok: "border-transparent text-ok",
      warn: "border-transparent bg-warn-soft text-warn",
      bad: "border-transparent bg-destructive-soft text-destructive",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ className, tone, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>): React.JSX.Element {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
