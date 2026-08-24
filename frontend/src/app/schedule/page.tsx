"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
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
    Download,
} from "lucide-react";
import clsx from "clsx";

import { AppHeader, SurfacePanel } from "@/components/AppShell";
import {
    Availability,
    fetchGroupMonthAvailability,
    fetchMyConfirmedSessions,
    fetchMyGroups,
    fetchOnboardingStatus,
    MyConfirmedSession,
    downloadPersonalScheduleIcs,
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
                "inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold",
                status === "Available" && "bg-emerald-400/15 text-emerald-200",
                status === "Maybe" && "bg-amber-300/15 text-amber-100",
                status === "No" && "bg-rose-400/15 text-rose-200",
                !status && "bg-slate-700/80 text-slate-300"
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

    const downloadSchedule = async () => {
        try {
            await downloadPersonalScheduleIcs(await getToken(), format(new Date(), "yyyy-MM-dd"));
        } catch (downloadError) {
            console.error("Failed to download schedule:", downloadError);
            setError("Could not download your calendar. Please retry.");
        }
    };

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <AppHeader />

            <main className="mx-auto w-full max-w-[1320px] px-4 py-7 sm:px-6">
                <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/70">Campaign ledger</p>
                        <h1 className="mt-1 font-serif text-3xl font-bold tracking-tight text-stone-100">My Schedule</h1>
                        <p className="mt-2 text-xs text-slate-400">Confirmed sessions across all of your groups.</p>
                    </div>
                    <div className="flex flex-wrap gap-2"><button onClick={() => void downloadSchedule()} className="inline-flex w-fit items-center gap-2 rounded-md border border-amber-200/30 bg-amber-200/10 px-3 py-2 text-xs font-bold text-amber-100 transition hover:bg-amber-200/15"><Download size={14} /> Export upcoming (.ics)</button><Link href="/app" className="inline-flex w-fit items-center gap-2 rounded-md border border-slate-600 bg-slate-800/70 px-3 py-2 text-xs font-bold text-slate-200 transition hover:bg-slate-700"><LayoutDashboard size={14} /> My Groups</Link></div>
                </div>

                {error ? (
                    <div className="mx-auto my-12 max-w-lg rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center dark:border-rose-900/50 dark:bg-rose-950/40">
                        <Shield className="mx-auto mb-3 text-rose-600 dark:text-rose-400" size={36} />
                        <p className="text-sm font-semibold text-rose-700 dark:text-rose-300">{error}</p>
                    </div>
                ) : isLoading ? (
                    <div className="space-y-5 animate-pulse">
                        <div className="h-44 rounded-xl border border-slate-700 bg-[#1a232e]" />
                        <div className="h-[38rem] rounded-xl border border-slate-700 bg-[#1a232e]" />
                    </div>
                ) : (
                    <div className="space-y-8">
                        <SurfacePanel className="p-5 sm:p-6">
                            <div className="mb-4 flex items-center gap-2">
                                <CalendarDays className="text-amber-200" size={18} />
                                <h2 className="font-serif text-lg font-bold text-stone-100">Upcoming sessions</h2>
                            </div>
                            {visibleUpcoming.length === 0 ? (
                                <p className="py-5 text-sm text-slate-400">No upcoming confirmed sessions.</p>
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
                                                    "rounded-lg border p-4 transition hover:border-amber-200/55 hover:bg-slate-800",
                                                    mismatch
                                                        ? "border-rose-400/45 bg-rose-400/[0.07]"
                                                        : "border-slate-700 bg-[#151d27]"
                                                )}
                                            >
                                                <p className="font-serif text-base font-bold text-stone-100">{format(new Date(`${session.day}T00:00:00`), "EEEE d MMMM")}</p>
                                                <p className="mt-1 text-xs font-semibold text-amber-100">{session.group_name}</p>
                                                <p className="mt-1 text-xs text-slate-300">{session.title || "Scheduled session"}{session.start_time ? ` · ${session.start_time.slice(0, 5)}` : ""}</p>
                                                <div className="mt-3 flex items-center justify-between gap-2">
                                                    <AvailabilityBadge status={status} />
                                                    <span className={clsx("text-[10px] font-bold", session.my_rsvp === "going" && "text-emerald-200", session.my_rsvp === "maybe" && "text-amber-100", session.my_rsvp === "declined" && "text-rose-200", !session.my_rsvp && "text-slate-500")}>{session.my_rsvp === "going" ? "Going" : session.my_rsvp === "maybe" ? "Maybe" : session.my_rsvp === "declined" ? "Declined" : "No RSVP"}</span>
                                                    {mismatch && <span className="text-[10px] font-bold text-rose-200">Unavailable</span>}
                                                </div>
                                            </Link>
                                        );
                                    })}
                                </div>
                            )}
                        </SurfacePanel>

                        <SurfacePanel className="p-4 sm:p-6">
                            <div className="mb-5 flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <CalendarDays className="text-amber-200" size={18} />
                                    <h2 className="font-serif text-lg font-bold text-stone-100">{format(currentDate, "MMMM yyyy")}</h2>
                                </div>
                                <div className="flex items-center gap-1">
                                    <button aria-label="Previous month" onClick={() => setCurrentDate((date) => subMonths(date, 1))} className="rounded-md p-2 text-slate-300 transition hover:bg-slate-700 hover:text-amber-100"><ChevronLeft size={17} /></button>
                                    <button aria-label="Next month" onClick={() => setCurrentDate((date) => addMonths(date, 1))} className="rounded-md p-2 text-slate-300 transition hover:bg-slate-700 hover:text-amber-100"><ChevronRight size={17} /></button>
                                </div>
                            </div>
                            <div className="mb-2 grid grid-cols-7 gap-1 sm:gap-2">
                                {DAYS.map((day) => <div key={day} className="py-1 text-center text-[10px] font-bold text-slate-500 sm:text-xs">{day}</div>)}
                            </div>
                            <div className="grid grid-cols-7 gap-1 sm:gap-2">
                                {startPadding.map((_, index) => <div key={`padding-${index}`} className="min-h-20 sm:min-h-28" />)}
                                {daysInMonth.map((day) => {
                                    const dayString = format(day, "yyyy-MM-dd");
                                    const sessions = sessionsForScheduleDay(monthSessions, dayString);
                                    return (
                                        <div key={dayString} className={clsx("min-h-20 rounded-md border p-1.5 sm:min-h-28 sm:p-2", sessions.length > 0 ? "border-amber-200/35 bg-amber-200/[0.05]" : "border-slate-700/60 bg-[#151d27]/65")}>
                                            <span className="text-[11px] font-bold text-slate-400">{format(day, "d")}</span>
                                            <div className="mt-1 space-y-1">
                                                {sessions.map((session) => {
                                                    const status = availabilityForConfirmedSession(session, availability, currentUserId);
                                                    return (
                                                        <Link key={session.id} href={`/groups/${session.group_id}`} title={`Open ${session.group_name}`} className={clsx("block truncate rounded px-1 py-0.5 text-[9px] font-bold sm:text-[11px]", isConfirmedSessionMismatch(status) ? "bg-rose-400/15 text-rose-200" : "bg-amber-200/12 text-amber-100")}>
                                                            ✓ {session.start_time ? `${session.start_time.slice(0, 5)} ` : ""}{session.group_name}
                                                        </Link>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </SurfacePanel>

                        {nextSession && <p className="sr-only">Next session: {nextSession.group_name} on {nextSession.day}</p>}
                    </div>
                )}
            </main>
        </div>
    );
}
