"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import {
    fetchGroupDetail,
    fetchGroupMonthAvailability,
    fetchMyGroups,
    updateGroupAvailability,
    GroupDetail,
    Availability,
    MyGroup,
} from "@/services/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
    format,
    addMonths,
    subMonths,
    startOfMonth,
    endOfMonth,
    eachDayOfInterval,
    isSameDay,
    isToday,
    getDay,
} from "date-fns";
import {
    CalendarDays,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    Crown,
    LayoutDashboard,
    Shield,
    Users,
    Check,
    HelpCircle,
    X,
} from "lucide-react";
import clsx from "clsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getDayIndex(date: Date) {
    const day = getDay(date);
    return day === 0 ? 6 : day - 1;
}

export default function GroupWorkspacePage({
    params,
}: {
    params: Promise<{ groupId: string }>;
}) {
    const { groupId } = use(params);
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();

    const [groupDetail, setGroupDetail] = useState<GroupDetail | null>(null);
    const [userGroups, setUserGroups] = useState<MyGroup[]>([]);
    const [availability, setAvailability] = useState<Availability[]>([]);
    const [currentDate, setCurrentDate] = useState<Date>(new Date());
    const [selectedDate, setSelectedDate] = useState<Date | null>(new Date());
    const [isLoading, setIsLoading] = useState(true);
    const [isUpdating, setIsUpdating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isGroupDropdownOpen, setIsGroupDropdownOpen] = useState(false);

    // 1. Load Group Detail and User Groups
    useEffect(() => {
        let active = true;
        const loadInitial = async () => {
            if (!isLoaded) return;
            try {
                setIsLoading(true);
                const token = await getToken();
                const [detail, myGroups] = await Promise.all([
                    fetchGroupDetail(groupId, token),
                    fetchMyGroups(token),
                ]);
                if (active) {
                    setGroupDetail(detail);
                    setUserGroups(myGroups);
                    setError(null);
                }
            } catch (err: unknown) {
                if (active) {
                    console.error("Failed to load group:", err);
                    const errorMsg = err instanceof Error ? err.message : "Failed to load group";
                    setError(errorMsg.includes("403") ? "You are not a member of this group." : "Failed to load group workspace.");
                }
            } finally {
                if (active) {
                    setIsLoading(false);
                }
            }
        };

        void loadInitial();
        return () => {
            active = false;
        };
    }, [isLoaded, getToken, groupId]);

    // 2. Load Monthly Availability
    useEffect(() => {
        let active = true;
        const loadMonth = async () => {
            if (!isLoaded || !groupDetail) return;
            try {
                const token = await getToken();
                const year = currentDate.getFullYear();
                const month = currentDate.getMonth() + 1;
                const data = await fetchGroupMonthAvailability(groupId, year, month, token);
                if (active) {
                    setAvailability(data);
                }
            } catch (err) {
                if (active) {
                    console.error("Failed to load availability:", err);
                }
            }
        };

        void loadMonth();
        return () => {
            active = false;
        };
    }, [isLoaded, getToken, groupId, currentDate, groupDetail]);

    // 3. Handle Current User Availability Cycling
    const handleToggleOwnAvailability = async (targetDate: Date) => {
        if (!groupDetail || isUpdating) return;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const currentUserMember = groupDetail.members.find(
            (m) => m.id === groupDetail.current_user_id
        );
        const currentUserName = currentUserMember?.display_name || "Me";

        const currentEntry = availability.find(
            (a) => a.date === dateStr && (a.user_name === currentUserName || a.user_name === currentUserMember?.display_name)
        );

        let nextStatus: string | null = "Available";
        if (currentEntry?.status === "Available") nextStatus = "Maybe";
        else if (currentEntry?.status === "Maybe") nextStatus = "No";
        else if (currentEntry?.status === "No") nextStatus = null;

        // Optimistic UI Update
        const optimistic = availability.filter(
            (a) => !(a.date === dateStr && a.user_name === currentUserName)
        );
        if (nextStatus) {
            optimistic.push({
                group_name: groupDetail.name,
                user_name: currentUserName,
                date: dateStr,
                status: nextStatus,
            });
        }
        setAvailability(optimistic);

        try {
            setIsUpdating(true);
            const token = await getToken();
            await updateGroupAvailability(groupId, dateStr, nextStatus, token);
        } catch (err) {
            console.error("Failed to update availability:", err);
            // Revert by refetching
            const token = await getToken();
            const year = currentDate.getFullYear();
            const month = currentDate.getMonth() + 1;
            const refetched = await fetchGroupMonthAvailability(groupId, year, month, token);
            setAvailability(refetched);
        } finally {
            setIsUpdating(false);
        }
    };

    // Calendar Calculations
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const daysInMonth = eachDayOfInterval({ start: monthStart, end: monthEnd });
    const startPadding = Array.from({ length: getDayIndex(monthStart) });

    const currentUserMember = groupDetail?.members.find(
        (m) => m.id === groupDetail.current_user_id
    );

    return (
        <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col">
            {/* Authenticated Top Navigation Shell */}
            <header className="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
                <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Link href="/app" className="flex items-center gap-3 group">
                            <div className="size-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 text-xl font-bold group-hover:scale-105 transition">
                                🎲
                            </div>
                            <span className="font-extrabold text-lg tracking-tight hidden sm:inline">
                                DnD Planner
                            </span>
                        </Link>

                        <div className="h-6 w-px bg-slate-200 dark:bg-slate-800 hidden sm:block" />

                        {/* Group Switcher Selector */}
                        <div className="relative">
                            <button
                                onClick={() => setIsGroupDropdownOpen((prev) => !prev)}
                                className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-xs font-bold transition shadow-sm"
                            >
                                <Users size={14} className="text-blue-600 dark:text-blue-400" />
                                <span className="truncate max-w-[150px] sm:max-w-[200px]">
                                    {groupDetail ? groupDetail.name : "Loading..."}
                                </span>
                                <ChevronDown size={14} className="text-slate-400" />
                            </button>

                            {isGroupDropdownOpen && (
                                <>
                                    <div
                                        className="fixed inset-0 z-40"
                                        onClick={() => setIsGroupDropdownOpen(false)}
                                    />
                                    <div className="absolute left-0 mt-2 w-56 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xl z-50 p-1.5 space-y-1">
                                        <div className="px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                                            My Groups
                                        </div>
                                        {userGroups.map((g) => (
                                            <button
                                                key={g.id}
                                                onClick={() => {
                                                    setIsGroupDropdownOpen(false);
                                                    if (g.id !== groupId) {
                                                        router.push(`/groups/${g.id}`);
                                                    }
                                                }}
                                                className={clsx(
                                                    "w-full text-left px-3 py-2 rounded-lg text-xs font-semibold flex items-center justify-between transition",
                                                    g.id === groupId
                                                        ? "bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 font-bold"
                                                        : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
                                                )}
                                            >
                                                <span className="truncate">{g.name}</span>
                                                {g.id === groupId && <Check size={14} />}
                                            </button>
                                        ))}
                                        <div className="pt-1 border-t border-slate-100 dark:border-slate-800">
                                            <Link
                                                href="/app"
                                                className="w-full text-left px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center gap-1.5 transition"
                                                onClick={() => setIsGroupDropdownOpen(false)}
                                            >
                                                <LayoutDashboard size={13} />
                                                <span>All Groups Dashboard</span>
                                            </Link>
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-3">
                        <Link
                            href="/app"
                            className="hidden md:flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition"
                        >
                            <LayoutDashboard size={14} />
                            <span>Dashboard</span>
                        </Link>
                        <div className="h-6 w-px bg-slate-200 dark:bg-slate-800" />
                        <ThemeToggle />
                        <div className="h-6 w-px bg-slate-200 dark:bg-slate-800" />
                        <UserButton />
                    </div>
                </div>
            </header>

            {/* Main Content Area */}
            <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
                {error ? (
                    <div className="rounded-2xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/40 p-8 text-center max-w-lg mx-auto my-12">
                        <Shield size={36} className="text-rose-600 dark:text-rose-400 mx-auto mb-3" />
                        <h2 className="text-lg font-bold text-rose-900 dark:text-rose-200 mb-2">Access Restricted</h2>
                        <p className="text-xs text-rose-700 dark:text-rose-300 mb-6">{error}</p>
                        <Link
                            href="/app"
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs shadow transition"
                        >
                            Return to My Groups Dashboard
                        </Link>
                    </div>
                ) : isLoading || !groupDetail ? (
                    <div className="space-y-6 animate-pulse">
                        <div className="h-20 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-6" />
                        <div className="h-96 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-6" />
                    </div>
                ) : (
                    <div className="space-y-8">
                        {/* Group Header Banner */}
                        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-6">
                            <div>
                                <div className="flex items-center gap-3 mb-1">
                                    <h1 className="text-2xl font-extrabold tracking-tight">{groupDetail.name}</h1>
                                    <span
                                        className={clsx(
                                            "inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded-full",
                                            groupDetail.role === "owner"
                                                ? "bg-amber-100 dark:bg-amber-950/70 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/50"
                                                : "bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300"
                                        )}
                                    >
                                        {groupDetail.role === "owner" && <Crown size={12} />}
                                        {groupDetail.role === "owner" ? "Group Owner" : "Member"}
                                    </span>
                                </div>
                                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mt-2">
                                    <span>Timezone: <strong className="text-slate-700 dark:text-slate-200">{groupDetail.timezone}</strong></span>
                                    <span>&bull;</span>
                                    <span>Playing as: <strong className="text-slate-700 dark:text-slate-200">{currentUserMember?.display_name || "Adventurer"}</strong></span>
                                </div>
                            </div>

                            {/* Month Navigator Controls */}
                            <div className="flex items-center gap-1 bg-slate-50 dark:bg-slate-800/80 p-1.5 rounded-xl border border-slate-200 dark:border-slate-700/60 self-start md:self-auto">
                                <button
                                    onClick={() => setCurrentDate(subMonths(currentDate, 12))}
                                    className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 text-xs font-bold transition"
                                    title="Previous Year"
                                >
                                    &laquo;
                                </button>
                                <button
                                    onClick={() => setCurrentDate(subMonths(currentDate, 1))}
                                    className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                                    title="Previous Month"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <span className="min-w-[130px] text-center text-xs font-bold text-slate-800 dark:text-slate-200 px-2">
                                    {format(currentDate, "MMMM yyyy")}
                                </span>
                                <button
                                    onClick={() => setCurrentDate(addMonths(currentDate, 1))}
                                    className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                                    title="Next Month"
                                >
                                    <ChevronRight size={16} />
                                </button>
                                <button
                                    onClick={() => setCurrentDate(addMonths(currentDate, 12))}
                                    className="p-1.5 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 text-xs font-bold transition"
                                    title="Next Year"
                                >
                                    &raquo;
                                </button>
                                <button
                                    onClick={() => {
                                        const now = new Date();
                                        setCurrentDate(now);
                                        setSelectedDate(now);
                                    }}
                                    className="ml-1 px-2.5 py-1 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
                                >
                                    Today
                                </button>
                            </div>
                        </div>

                        {/* Interactive Availability Matrix & Calendar */}
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                            {/* Left 2 Cols: Group Availability Calendar Grid */}
                            <div className="lg:col-span-2 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
                                <div className="flex items-center justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <CalendarDays size={18} className="text-blue-600 dark:text-blue-400" />
                                        <h2 className="text-base font-bold">Group Calendar</h2>
                                    </div>
                                    <div className="text-[11px] text-slate-400 flex items-center gap-3">
                                        <span className="flex items-center gap-1">
                                            <span className="size-2.5 rounded-full bg-emerald-500 inline-block" /> Available
                                        </span>
                                        <span className="flex items-center gap-1">
                                            <span className="size-2.5 rounded-full bg-amber-500 inline-block" /> Maybe
                                        </span>
                                        <span className="flex items-center gap-1">
                                            <span className="size-2.5 rounded-full bg-rose-500 inline-block" /> No
                                        </span>
                                    </div>
                                </div>

                                <p className="text-xs text-slate-500 dark:text-slate-400 mb-6">
                                    Click any date in the calendar below to toggle your own availability (<strong>Available &rarr; Maybe &rarr; No &rarr; Clear</strong>).
                                </p>

                                {/* Month Days Grid */}
                                <div className="grid grid-cols-7 gap-2 mb-2">
                                    {DAYS.map((day) => (
                                        <div key={day} className="text-center text-[11px] font-bold text-slate-400 py-1">
                                            {day}
                                        </div>
                                    ))}
                                </div>

                                <div className="grid grid-cols-7 gap-2">
                                    {startPadding.map((_, i) => (
                                        <div key={`pad-${i}`} className="min-h-[85px] rounded-xl bg-slate-50/50 dark:bg-slate-900/30 border border-transparent" />
                                    ))}

                                    {daysInMonth.map((date) => {
                                        const dateStr = format(date, "yyyy-MM-dd");
                                        const dayEntries = availability.filter((a) => a.date === dateStr);
                                        const availableCount = dayEntries.filter((a) => a.status === "Available").length;
                                        const maybeCount = dayEntries.filter((a) => a.status === "Maybe").length;
                                        const noCount = dayEntries.filter((a) => a.status === "No").length;

                                        const ownEntry = dayEntries.find(
                                            (a) => a.user_name === currentUserMember?.display_name
                                        );

                                        const isSelected = selectedDate && isSameDay(date, selectedDate);
                                        const isCurrentDay = isToday(date);

                                        return (
                                            <button
                                                key={dateStr}
                                                onClick={() => {
                                                    setSelectedDate(date);
                                                    void handleToggleOwnAvailability(date);
                                                }}
                                                className={clsx(
                                                    "min-h-[85px] p-2 rounded-xl border text-left transition flex flex-col justify-between group cursor-pointer relative",
                                                    isSelected
                                                        ? "ring-2 ring-blue-500 dark:ring-blue-400 border-blue-500"
                                                        : "border-slate-200/80 dark:border-slate-800 hover:border-blue-300 dark:hover:border-blue-700",
                                                    isCurrentDay
                                                        ? "bg-blue-50/40 dark:bg-blue-950/20 font-bold"
                                                        : "bg-white dark:bg-slate-900/90"
                                                )}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <span
                                                        className={clsx(
                                                            "text-xs font-bold size-5 flex items-center justify-center rounded-full",
                                                            isCurrentDay
                                                                ? "bg-blue-600 text-white"
                                                                : "text-slate-700 dark:text-slate-300"
                                                        )}
                                                    >
                                                        {format(date, "d")}
                                                    </span>

                                                    {ownEntry && (
                                                        <span
                                                            className={clsx(
                                                                "text-[10px] font-extrabold px-1.5 py-0.2 rounded",
                                                                ownEntry.status === "Available" && "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
                                                                ownEntry.status === "Maybe" && "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
                                                                ownEntry.status === "No" && "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"
                                                            )}
                                                        >
                                                            {ownEntry.status === "Available" ? "✓" : ownEntry.status === "Maybe" ? "?" : "✗"}
                                                        </span>
                                                    )}
                                                </div>

                                                {/* Group counts badge */}
                                                <div className="space-y-1 mt-1">
                                                    {availableCount > 0 && (
                                                        <div className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                                                            <span>🟢</span> {availableCount}/{groupDetail.members.length}
                                                        </div>
                                                    )}
                                                    {maybeCount > 0 && availableCount === 0 && (
                                                        <div className="text-[10px] font-semibold text-amber-600 dark:text-amber-400 flex items-center gap-1">
                                                            <span>🟡</span> {maybeCount} maybe
                                                        </div>
                                                    )}
                                                    {availableCount === 0 && maybeCount === 0 && noCount > 0 && (
                                                        <div className="text-[10px] font-semibold text-slate-400">
                                                            {noCount} no
                                                        </div>
                                                    )}
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Right 1 Col: Selected Day Roster & Player Matrix */}
                            <div className="space-y-6">
                                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
                                    <div className="flex items-center justify-between mb-4">
                                        <h3 className="font-bold text-sm">
                                            {selectedDate ? format(selectedDate, "EEEE, MMMM d") : "Select a day"}
                                        </h3>
                                        {selectedDate && (
                                            <button
                                                onClick={() => void handleToggleOwnAvailability(selectedDate)}
                                                className="text-xs font-semibold px-2.5 py-1 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/60 transition cursor-pointer"
                                            >
                                                Toggle My Status
                                            </button>
                                        )}
                                    </div>

                                    {selectedDate && (
                                        <div className="space-y-2.5">
                                            {groupDetail.members.map((member) => {
                                                const dateStr = format(selectedDate, "yyyy-MM-dd");
                                                const memberEntry = availability.find(
                                                    (a) => a.date === dateStr && a.user_name === member.display_name
                                                );
                                                const isSelf = member.id === groupDetail.current_user_id;

                                                return (
                                                    <div
                                                        key={member.id}
                                                        className={clsx(
                                                            "p-3 rounded-xl border flex items-center justify-between text-xs transition",
                                                            isSelf
                                                                ? "border-blue-200 dark:border-blue-900/60 bg-blue-50/40 dark:bg-blue-950/30 font-semibold"
                                                                : "border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50"
                                                        )}
                                                    >
                                                        <div className="flex items-center gap-2.5">
                                                            <div className="size-7 rounded-lg bg-slate-200 dark:bg-slate-800 flex items-center justify-center font-bold text-[11px] text-slate-700 dark:text-slate-300">
                                                                {member.display_name.slice(0, 2).toUpperCase()}
                                                            </div>
                                                            <div>
                                                                <span className="font-medium text-slate-900 dark:text-slate-100">
                                                                    {member.display_name} {isSelf && <span className="text-[10px] text-blue-600 dark:text-blue-400">(You)</span>}
                                                                </span>
                                                                {member.role === "owner" && (
                                                                    <span className="ml-1.5 text-[10px] text-amber-600 font-bold">DM</span>
                                                                )}
                                                            </div>
                                                        </div>

                                                        <div>
                                                            {memberEntry?.status === "Available" ? (
                                                                <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300 font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/80">
                                                                    <Check size={12} /> Available
                                                                </span>
                                                            ) : memberEntry?.status === "Maybe" ? (
                                                                <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300 font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/80">
                                                                    <HelpCircle size={12} /> Maybe
                                                                </span>
                                                            ) : memberEntry?.status === "No" ? (
                                                                <span className="inline-flex items-center gap-1 text-rose-700 dark:text-rose-300 font-bold px-2 py-0.5 rounded-full bg-rose-100 dark:bg-rose-950/80">
                                                                    <X size={12} /> No
                                                                </span>
                                                            ) : (
                                                                <span className="text-slate-400 text-[11px]">Unset</span>
                                                            )}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>

                                {/* Group Members Card */}
                                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
                                    <h3 className="font-bold text-sm mb-3 flex items-center gap-2">
                                        <Users size={16} className="text-slate-400" />
                                        <span>Roster ({groupDetail.members.length})</span>
                                    </h3>
                                    <div className="flex flex-wrap gap-2">
                                        {groupDetail.members.map((m) => (
                                            <span
                                                key={m.id}
                                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs text-slate-700 dark:text-slate-300"
                                            >
                                                <span>{m.display_name}</span>
                                                {m.role === "owner" && <Crown size={12} className="text-amber-500" />}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
