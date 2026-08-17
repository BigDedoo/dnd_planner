"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { CalendarDays, Dices, LayoutDashboard } from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";

export function AppBrand({ compact = false }: { compact?: boolean }) {
    return (
        <Link href="/app" className="group flex items-center gap-2.5">
            <span className="flex size-9 items-center justify-center rounded-lg border border-amber-300/35 bg-amber-300/10 text-amber-200 shadow-[0_0_18px_rgba(213,167,91,0.12)] transition group-hover:border-amber-300/70 group-hover:text-amber-100">
                <Dices size={19} strokeWidth={1.5} />
            </span>
            <span className={compact ? "hidden sm:block" : ""}>
                <span className="block font-serif text-base font-bold tracking-tight text-stone-100">DnD Planner</span>
                <span className="block text-[9px] font-bold uppercase tracking-[0.2em] text-amber-300/65">Campaign calendar</span>
            </span>
        </Link>
    );
}

export function AppHeader({ context }: { context?: ReactNode }) {
    return (
        <header className="sticky top-0 z-50 border-b border-slate-700/70 bg-[#141c26]/95 shadow-[0_8px_30px_rgba(0,0,0,0.22)] backdrop-blur-xl">
            <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-3 px-4 sm:px-6">
                <div className="flex min-w-0 items-center gap-3 sm:gap-5">
                    <AppBrand compact />
                    {context && <span className="hidden h-6 w-px bg-slate-700 sm:block" />}
                    {context}
                </div>
                <nav className="flex shrink-0 items-center gap-1 sm:gap-2">
                    <Link href="/schedule" className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 sm:px-3">
                        <CalendarDays size={14} />
                        <span className="hidden md:inline">My Schedule</span>
                    </Link>
                    <Link href="/app" className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 sm:px-3">
                        <LayoutDashboard size={14} />
                        <span className="hidden md:inline">Dashboard</span>
                    </Link>
                    <span className="mx-1 hidden h-5 w-px bg-slate-700 sm:block" />
                    <ThemeToggle />
                    <UserButton />
                </nav>
            </div>
        </header>
    );
}

export function SurfacePanel({ className = "", children }: { className?: string; children: ReactNode }) {
    return <section className={`rounded-xl border border-slate-700/80 bg-[#1a232e]/92 shadow-[0_12px_28px_rgba(0,0,0,0.16)] ${className}`}>{children}</section>;
}
