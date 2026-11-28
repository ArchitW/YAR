"use client";

import * as React from "react";
import { ChevronDown, Circle } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export interface ChainOfThoughtProps {
  children: React.ReactNode;
  className?: string;
}

export function ChainOfThought({ children, className }: ChainOfThoughtProps) {
  const childrenArray = React.Children.toArray(children);

  return (
    <div className={cn("space-y-0", className)}>
      {childrenArray.map((child, index) => (
        <React.Fragment key={index}>
          {React.isValidElement(child)
            ? React.cloneElement(
                child as React.ReactElement<ChainOfThoughtStepProps>,
                { isLast: index === childrenArray.length - 1 }
              )
            : child}
        </React.Fragment>
      ))}
    </div>
  );
}

export interface ChainOfThoughtStepProps
  extends React.ComponentPropsWithoutRef<typeof Collapsible> {
  children: React.ReactNode;
  className?: string;
  isLast?: boolean;
}

export function ChainOfThoughtStep({
  children,
  className,
  isLast = false,
  ...props
}: ChainOfThoughtStepProps) {
  return (
    <Collapsible
      className={cn("group", className)}
      data-last={isLast ? "true" : "false"}
      {...props}
    >
      {children}
      <div className="flex justify-start group-data-[last=true]:hidden">
        <div className="bg-primary/20 ml-1.75 h-4 w-px" />
      </div>
    </Collapsible>
  );
}

export interface ChainOfThoughtTriggerProps
  extends React.ComponentPropsWithoutRef<typeof CollapsibleTrigger> {
  children: React.ReactNode;
  className?: string;
  leftIcon?: React.ReactNode;
  swapIconOnHover?: boolean;
}

export function ChainOfThoughtTrigger({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: ChainOfThoughtTriggerProps) {
  return (
    <CollapsibleTrigger
      className={cn(
        "group/trigger text-muted-foreground hover:text-foreground flex cursor-pointer items-center justify-start gap-2 text-left text-xs transition-colors",
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-2">
        {leftIcon ? (
          <span className="relative inline-flex size-4 items-center justify-center">
            <span
              className={cn(
                "transition-opacity",
                swapIconOnHover && "group-hover/trigger:opacity-0"
              )}
            >
              {leftIcon}
            </span>
            {swapIconOnHover && (
              <ChevronDown className="size-3.5 absolute opacity-0 transition-opacity group-hover/trigger:opacity-100 group-data-[state=open]:rotate-180" />
            )}
          </span>
        ) : (
          <span className="relative inline-flex size-4 items-center justify-center">
            <Circle className="size-2 fill-current" />
          </span>
        )}
        <span className="font-medium">{children}</span>
      </div>
      {!leftIcon && (
        <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
      )}
    </CollapsibleTrigger>
  );
}

export interface ChainOfThoughtContentProps
  extends React.ComponentPropsWithoutRef<typeof CollapsibleContent> {
  children: React.ReactNode;
  className?: string;
}

export function ChainOfThoughtContent({
  children,
  className,
  ...props
}: ChainOfThoughtContentProps) {
  return (
    <CollapsibleContent
      className={cn(
        "text-popover-foreground overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className
      )}
      {...props}
    >
      <div className="grid grid-cols-[16px_1fr] gap-x-2 pt-1.5">
        <div className="flex justify-center">
          <div className="bg-primary/20 h-full w-px" />
        </div>
        <div className="space-y-1.5 pb-1">{children}</div>
      </div>
    </CollapsibleContent>
  );
}

export interface ChainOfThoughtItemProps
  extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
}

export function ChainOfThoughtItem({
  children,
  className,
  ...props
}: ChainOfThoughtItemProps) {
  return (
    <div
      className={cn("text-muted-foreground text-xs leading-relaxed", className)}
      {...props}
    >
      {children}
    </div>
  );
}
