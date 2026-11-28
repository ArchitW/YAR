"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export interface StepsProps
  extends React.ComponentPropsWithoutRef<typeof Collapsible> {
  children: React.ReactNode;
  className?: string;
}

export function Steps({
  children,
  className,
  defaultOpen = true,
  ...props
}: StepsProps) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className={cn("group text-xs", className)}
      {...props}
    >
      {children}
    </Collapsible>
  );
}

export interface StepsTriggerProps
  extends React.ComponentPropsWithoutRef<typeof CollapsibleTrigger> {
  children: React.ReactNode;
  className?: string;
  leftIcon?: React.ReactNode;
  swapIconOnHover?: boolean;
}

export function StepsTrigger({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: StepsTriggerProps) {
  return (
    <CollapsibleTrigger
      className={cn(
        "group/trigger text-muted-foreground hover:text-foreground flex w-full cursor-pointer items-center justify-between gap-2 text-left text-xs transition-colors",
        className
      )}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2">
        {leftIcon && (
          <span className="relative inline-flex size-4 shrink-0 items-center justify-center">
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
        )}
        <span className="truncate font-medium">{children}</span>
      </div>
      <ChevronDown className="size-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
    </CollapsibleTrigger>
  );
}

export interface StepsContentProps
  extends React.ComponentPropsWithoutRef<typeof CollapsibleContent> {
  children: React.ReactNode;
  className?: string;
  bar?: React.ReactNode;
}

export function StepsContent({
  children,
  className,
  bar = <StepsBar />,
  ...props
}: StepsContentProps) {
  return (
    <CollapsibleContent
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className
      )}
      {...props}
    >
      <div className="mt-2 flex gap-2.5 pl-1.5">
        {bar}
        <div className="flex-1 space-y-1.5 pb-0.5">{children}</div>
      </div>
    </CollapsibleContent>
  );
}

export interface StepsBarProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
}

export function StepsBar({ className, ...props }: StepsBarProps) {
  return (
    <div
      aria-hidden="true"
      className={cn("bg-border w-px shrink-0 self-stretch", className)}
      {...props}
    />
  );
}

export interface StepsItemProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
}

export function StepsItem({ children, className, ...props }: StepsItemProps) {
  return (
    <div
      className={cn(
        "text-muted-foreground flex items-center gap-2 text-xs leading-relaxed",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
