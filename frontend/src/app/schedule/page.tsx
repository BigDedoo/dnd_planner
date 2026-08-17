"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import {
    addMonths,
    eachDayOfInterval,
    endOfMonth,
    format,
    getDay,
    startOfMonth,
    subMonths,
} from "date-fns";
import {
    CalendarDays,
    ChevronLeft,
    ChevronRight,
    LayoutDashboard,
    Shield,
} from "lucide-react";
import clsx from "clsx";

import { ThemeToggle } from "@/components/ThemeToggle";
import {
    Availability,
    fetchGroupMonthAvailability,
    fetchMyConfirmedSessions,
    fetchMyGroups,
    fetchOnboardingStatus,
    MyConfirmedSession,
} from "@/services/api";
import {
    availabilityForConfirmedSession,
    availabilityLabel,
    isConfirmedSessionMismatch,
    sessionsForScheduleDay,
    upcomingConfirmedSessions,
} from "@/lib/mySchedule";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const LAST_SUPPORTED_DAY = "9999-12-31";

function getDayIndex(day: Date) {
    const weekday = getDay(day);
    return weekday === 0 ? 6 : weekday - 1;
}

function AvailabilityBadge({ status }: { status: string | null }) {
    const label = availabilityLabel(status);
    return (
        <span
            className={clsx(
                "inline-flex rounded-full px-2 py-0.5 text-[11px] font-bold",
                status === "Available" && "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300",
                status === "Maybe" && "bg-amber-100 text-amber-800 dark:bg-amber-950/70 dark:text-amber-300",
                status === "No" && "bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300",
                !status && "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
            )}
        >
            {label}
        </span>
    );
}

export default function MySchedulePage() {
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const [currentDate, setCurrentDate] = useState(() => new Date());
    const [upcoming, setUpcoming] = useState<MyConfirmedSession[]>([]);
    const [monthSessions, setMonthSessions] = useState<MyConfirmedSession[]>([]);
    const [availability, setAvailability] = useState<Availability[]>([]);
    const [currentUserId, setCurrentUserId] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;

        const loadSchedule = async () => {
            if (!isLoaded) return;
            try {
                setIsLoading(true);
                const token = await getToken();
                const onboarding = await fetchOnboardingStatus(token);
                if (!onboarding.linked) {
                    router.replace("/onboarding?next=/schedule");
                    return;
                }

                const monthStart = format(startOfMonth(currentDate), "yyyy-MM-dd");
                const monthEnd = format(endOfMonth(currentDate), "yyyy-MM-dd");
                const today = format(new Date(), "yyyy-MM-dd");
                const [groups, futureSessions, sessionsThisMonth] = await Promise.all([
                    fetchMyGroups(token),
                    fetchMyConfirmedSessions(today, LAST_SUPPORTED_DAY, token),
                    fetchMyConfirmedSessions(monthStart, monthEnd, token),
                ]);
                const upcomingSessions = upcomingConfirmedSessions(futureSessions, today);
                const sessionsNeedingAvailability = [...upcomingSessions, ...sessionsThisMonth];
                const queriedMonths = new Set<string>();
                const availabilityRequests = sessionsNeedingAvailability.flatMap((session) => {
                    const month = session.day.slice(0, 7);
                    const key = `${session.group_id}:${month}`;
                    if (queriedMonths.has(key)) return [];
                    queriedMonths.add(key);
                    const group = groups.find((candidate) => candidate.id === session.group_id);
                    if (!group) return [];
                    const [year, monthNumber] = month.split("-").map(Number);
                    return [fetchGroupMonthAvailability(group.id, year, monthNumber, token)];
                });
                const availabilityByGroupMonth = await Promise.all(availabilityRequests);

                if (active) {
                    setCurrentUserId(onboarding.user_id);
                    setUpcoming(upcomingSessions);
                    setMonthSessions(sessionsThisMonth);
                    setAvailability(availabilityByGroupMonth.flat());
                    setError(null);
                }
            } catch (loadError) {
                if (active) {
                    console.error("Failed to load My Schedule:", loadError);
                    setError("Failed to load your schedule. Please try refreshing.");
                }
            } finally {
                if (active) setIsLoading(false);
            }
        };

        void loadSchedule();
        return () => {
            active = false;
        };
    }, [currentDate, getToken, isLoaded, router]);

    const monthStart = startOfMonth(currentDate);
    const daysInMonth = eachDayOfInterval({
        start: monthStart,
        end: endOfMonth(currentDate),
    });
    const startPadding = Array.from({ length: getDayIndex(monthStart) });
    const nextSession = upcoming[0];
    const visibleUpcoming = useMemo(() => upcoming, [upcoming]);

    return (
        <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
            <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/80 backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/80">
                <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
                    <Link href="/app" className="flex items-center gap-3 group">
                        <div className="flex size-10 items-center justify-center rounded-xl bg-blue-600 text-xl font-bold text-white shadow-md shadow-blue-500/20 transition group-hover:scale-105">
                            🎲
                        </div>
                        <span className="hidden text-lg font-extrabold tracking-tight sm:inline">DnD Planner</span>
                    </Link>
                    <div className="flex items-center gap-2 sm:gap-3">
                        <Link
                            href="/app"
                            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                        >
                            <LayoutDashboard size={14} />
                            <span className="hidden sm:inline">Dashboard</span>
                        </Link>
                        <span className="hidden h-6 w-px bg-slate-200 dark:bg-slate-800 sm:block" />
                        <ThemeToggle />
                        <span className="h-6 w-px bg-slate-200 dark:bg-slate-800" />
                        <UserButton />
                    </div>
                </div>
            </header>

            <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
                <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <p className="text-xs font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">Personal calendar</p>
                        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">My Schedule</h1>
                        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">Confirmed sessions across all of your groups.</p>
                    </div>
                    <Link
                        href="/app"
                        className="inline-flex w-fit items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                        <LayoutDashboard size={14} /> My Groups
                    </Link>
                </div>

                {error ? (
                    <div className="mx-auto my-12 max-w-lg rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center dark:border-rose-900/50 dark:bg-rose-950/40">
                        <Shield className="mx-auto mb-3 text-rose-600 dark:text-rose-400" size={36} />
                        <p className="text-sm font-semibold text-rose-700 dark:text-rose-300">{error}</p>
                    </div>
                ) : isLoading ? (
                    <div className="space-y-6 animate-pulse">
                        <div className="h-44 rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900" />
                        <div className="h-[38rem] rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900" />
                    </div>
                ) : (
                    <div className="space-y-8">
                        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
                            <div className="mb-4 flex items-center gap-2">
                                <CalendarDays className="text-blue-600 dark:text-blue-400" size={18} />
                                <h2 className="text-base font-extrabold">Upcoming sessions</h2>
                            </div>
                            {visibleUpcoming.length === 0 ? (
                                <p className="py-5 text-sm text-slate-500 dark:text-slate-400">No upcoming confirmed sessions.</p>
                            ) : (
                                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                                    {visibleUpcoming.map((session) => {
                                        const status = availabilityForConfirmedSession(session, availability, currentUserId);
                                        const mismatch = isConfirmedSessionMismatch(status);
                                        return (
                                            <Link
                                                key={session.id}
                                                href={`/groups/${session.group_id}`}
                                                className={clsx(
                                                    "rounded-xl border p-4 transition hover:border-blue-400 hover:shadow-sm",
                                                    mismatch
                                                        ? "border-rose-300 bg-rose-50/60 dark:border-rose-900/70 dark:bg-rose-950/20"
                                                        : "border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-950/30"
                                                )}
                                            >
                                                <p className="text-sm font-extrabold">{format(new Date(`${session.day}T00:00:00`), "EEEE d MMMM")}</p>
                                                <p className="mt-1 text-sm font-semibold text-blue-700 dark:text-blue-300">{session.group_name}</p>
                                                <div className="mt-3 flex items-center justify-between gap-2">
                                                    <AvailabilityBadge status={status} />
                                                    {mismatch && <span className="text-[11px] font-bold text-rose-700 dark:text-rose-300">Confirmed while unavailable</span>}
                                                </div>
                                            </Link>
                                        );
                                    })}
                                </div>
                            )}
                        </section>

                        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
                            <div className="mb-5 flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <CalendarDays className="text-violet-600 dark:text-violet-400" size={18} />
                                    <h2 className="text-base font-extrabold">{format(currentDate, "MMMM yyyy")}</h2>
                                </div>
                                <div className="flex items-center gap-1">
                                    <button aria-label="Previous month" onClick={() => setCurrentDate((date) => subMonths(date, 1))} className="rounded-lg p-2 transition hover:bg-slate-100 dark:hover:bg-slate-800"><ChevronLeft size={17} /></button>
                                    <button aria-label="Next month" onClick={() => setCurrentDate((date) => addMonths(date, 1))} className="rounded-lg p-2 transition hover:bg-slate-100 dark:hover:bg-slate-800"><ChevronRight size={17} /></button>
                                </div>
                            </div>
                            <div className="mb-2 grid grid-cols-7 gap-1 sm:gap-2">
                                {DAYS.map((day) => <div key={day} className="py-1 text-center text-[10px] font-bold text-slate-400 sm:text-xs">{day}</div>)}
                            </div>
                            <div className="grid grid-cols-7 gap-1 sm:gap-2">
                                {startPadding.map((_, index) => <div key={`padding-${index}`} className="min-h-20 sm:min-h-28" />)}
                                {daysInMonth.map((day) => {
                                    const dayString = format(day, "yyyy-MM-dd");
                                    const sessions = sessionsForScheduleDay(monthSessions, dayString);
                                    return (
                                        <div key={dayString} className={clsx("min-h-20 rounded-lg border p-1.5 sm:min-h-28 sm:p-2", sessions.length > 0 ? "border-violet-300 bg-violet-50/60 dark:border-violet-900/70 dark:bg-violet-950/20" : "border-slate-100 bg-slate-50/50 dark:border-slate-800/70 dark:bg-slate-950/20")}>
                                            <span className="text-[11px] font-bold text-slate-500 dark:text-slate-400">{format(day, "d")}</span>
                                            <div className="mt-1 space-y-1">
                                                {sessions.map((session) => {
                                                    const status = availabilityForConfirmedSession(session, availability, currentUserId);
                                                    return (
                                                        <Link key={session.id} href={`/groups/${session.group_id}`} title={`Open ${session.group_name}`} className={clsx("block truncate rounded px-1 py-0.5 text-[9px] font-bold sm:text-[11px]", isConfirmedSessionMismatch(status) ? "bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300" : "bg-violet-100 text-violet-800 dark:bg-violet-950/70 dark:text-violet-300")}>
                                                            ✓ {session.group_name}
                                                        </Link>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </section>

                        {nextSession && <p className="sr-only">Next session: {nextSession.group_name} on {nextSession.day}</p>}
                    </div>
                )}
            </main>
        </div>
    );
}
