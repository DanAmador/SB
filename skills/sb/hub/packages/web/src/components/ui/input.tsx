import type * as React from "react";
import { cn } from "@/lib/utils";

const field = "rounded-md border border-input bg-card px-2.5 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50";

export function Input({ className, ...props }: React.ComponentProps<"input">): React.JSX.Element {
  return <input className={cn(field, "h-8 min-w-0", className)} {...props} />;
}
export function Textarea({ className, ...props }: React.ComponentProps<"textarea">): React.JSX.Element {
  return <textarea className={cn(field, "min-h-16 w-full py-2 leading-snug", className)} {...props} />;
}
export function Select({ className, ...props }: React.ComponentProps<"select">): React.JSX.Element {
  return <select className={cn(field, "h-8 min-w-0 pr-7", className)} {...props} />;
}
export function Label({ className, ...props }: React.ComponentProps<"label">): React.JSX.Element {
  return <label className={cn("flex flex-col gap-1.5 text-xs font-medium text-muted-foreground", className)} {...props} />;
}
