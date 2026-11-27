import * as React from "react";
import { HoverCard as RadixHoverCard } from "radix-ui";
import { cn } from "@/lib/utils";

export const HoverCard = RadixHoverCard.Root;
export const HoverCardTrigger = RadixHoverCard.Trigger;

export const HoverCardContent = React.forwardRef<
  React.ElementRef<typeof RadixHoverCard.Content>,
  React.ComponentPropsWithoutRef<typeof RadixHoverCard.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <RadixHoverCard.Portal>
    <RadixHoverCard.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        "z-50 w-64 rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none animate-in fade-in-0 zoom-in-95",
        className
      )}
      {...props}
    />
  </RadixHoverCard.Portal>
));
HoverCardContent.displayName = "HoverCardContent";
