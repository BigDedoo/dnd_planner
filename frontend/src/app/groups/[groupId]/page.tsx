"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import {
    fetchGroupDetail,
    fetchGroupMonthAvailability,
    fetchGroupConfirmedSessions,
    fetchMyConfirmedSessions,
    fetchMyGroups,
    confirmGroupSession,
    cancelGroupSession,
    fetchGroupInviteStatus,
    generateGroupInvite,
    revokeGroupInvite,
    fetchOnboardingStatus,
    updateGroupAvailability,
    updateOwnGroupNickname,
    ConfirmedSession,
    GroupDetail,
    Availability,
    MyConfirmedSession,
    MyGroup,
    GroupInviteStatus,
} from "@/services/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import { otherGroupConfirmedSessionsForDay } from "@/lib/confirmedSessions";
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
    KeyRound,
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
    const [confirmedSessions, setConfirmedSessions] = useState<ConfirmedSession[]>([]);
    const [myConfirmedSessions, setMyConfirmedSessions] = useState<MyConfirmedSession[]>([]);
    const [currentDate, setCurrentDate] = useState<Date>(new Date());
    const [selectedDate, setSelectedDate] = useState<Date | null>(new Date());
    const [isLoading, setIsLoading] = useState(true);
    const [isUpdating, setIsUpdating] = useState(false);
    const [isConfirmationUpdating, setIsConfirmationUpdating] = useState(false);
    const [availabilityWarning, setAvailabilityWarning] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isGroupDropdownOpen, setIsGroupDropdownOpen] = useState(false);
    const [inviteStatus, setInviteStatus] = useState<GroupInviteStatus | null>(null);
    const [inviteCode, setInviteCode] = useState<string | null>(null);
    const [isInviteUpdating, setIsInviteUpdating] = useState(false);
    const [inviteError, setInviteError] = useState<string | null>(null);
    const [nicknameDraft, setNicknameDraft] = useState("");
    const [isNicknameUpdating, setIsNicknameUpdating] = useState(false);
    const [nicknameError, setNicknameError] = useState<string | null>(null);

    // 1. Load Group Detail and User Groups
    useEffect(() => {
        let active = true;
        const loadInitial = async () => {
            if (!isLoaded) return;
            try {
                setIsLoading(true);
                const token = await getToken();
                const onboarding = await fetchOnboardingStatus(token);
                if (!onboarding.linked) {
                    router.replace(`/onboarding?next=/groups/${groupId}`);
                    return;
                }
                const [detail, myGroups] = await Promise.all([
                    fetchGroupDetail(groupId, token),
                    fetchMyGroups(token),
                ]);
                if (active) {
                    setGroupDetail(detail);
                    setUserGroups(myGroups);
                    setNicknameDraft(
                        detail.members.find((member) => member.id === detail.current_user_id)?.nickname || ""
                    );
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
    }, [isLoaded, getToken, groupId, router]);

    useEffect(() => {
        let active = true;
        const loadInviteStatus = async () => {
            if (!isLoaded || groupDetail?.role !== "owner") {
                if (active) {
                    setInviteStatus(null);
                    setInviteCode(null);
                }
                return;
            }
            try {
                const token = await getToken();
                const status = await fetchGroupInviteStatus(groupId, token);
                if (active) setInviteStatus(status);
            } catch (err) {
                console.error("Failed to load invite status:", err);
            }
        };

        void loadInviteStatus();
        return () => {
            active = false;
        };
    }, [isLoaded, getToken, groupDetail?.role, groupId]);

    // 2. Load Monthly Availability
    useEffect(() => {
        let active = true;
        const loadMonth = async () => {
            if (!isLoaded || !groupDetail) return;
            try {
                const token = await getToken();
                const year = currentDate.getFullYear();
                const month = currentDate.getMonth() + 1;
                const start = format(startOfMonth(currentDate), "yyyy-MM-dd");
                const end = format(endOfMonth(currentDate), "yyyy-MM-dd");
                const [availabilityData, groupSessions, personalSessions] = await Promise.all([
                    fetchGroupMonthAvailability(groupId, year, month, token),
                    fetchGroupConfirmedSessions(groupId, start, end, token),
                    fetchMyConfirmedSessions(start, end, token),
                ]);
                if (active) {
                    setAvailability(availabilityData);
                    setConfirmedSessions(groupSessions);
                    setMyConfirmedSessions(personalSessions);
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
        const otherGroupSessions = otherGroupConfirmedSessionsForDay(
            myConfirmedSessions,
            groupId,
            dateStr
        );
        if (otherGroupSessions.length > 0) {
            const names = otherGroupSessions.map((session) => session.group_name).join(", ");
            setAvailabilityWarning(
                `You already have a confirmed session with ${names} on this date.`
            );
        } else {
            setAvailabilityWarning(null);
        }

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

    const handleToggleConfirmation = async (targetDate: Date) => {
        if (!groupDetail || groupDetail.role !== "owner" || isConfirmationUpdating) return;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const existing = confirmedSessions.find((session) => session.day === dateStr);
        try {
            setIsConfirmationUpdating(true);
            const token = await getToken();
            if (existing) {
                await cancelGroupSession(groupId, dateStr, token);
                setConfirmedSessions((sessions) =>
                    sessions.filter((session) => session.id !== existing.id)
                );
                setMyConfirmedSessions((sessions) =>
                    sessions.filter((session) => session.id !== existing.id)
                );
            } else {
                const confirmed = await confirmGroupSession(groupId, dateStr, token);
                const personalConfirmed: MyConfirmedSession = {
                    ...confirmed,
                    group_name: groupDetail.name,
                };
                setConfirmedSessions((sessions) => [...sessions, confirmed]);
                setMyConfirmedSessions((sessions) => [...sessions, personalConfirmed]);
            }
        } catch (err) {
            console.error("Failed to update confirmed session:", err);
            setError("Could not update the confirmed session.");
        } finally {
            setIsConfirmationUpdating(false);
        }
    };

    const handleGenerateInvite = async () => {
        if (!groupDetail || groupDetail.role !== "owner" || isInviteUpdating) return;
        try {
            setIsInviteUpdating(true);
            setInviteError(null);
            const token = await getToken();
            const invite = await generateGroupInvite(groupId, token);
            setInviteCode(invite.code);
            setInviteStatus({
                active: true,
                created_at: invite.created_at,
                use_count: invite.use_count,
            });
        } catch (err) {
            console.error("Failed to generate invite:", err);
            setInviteError("Could not generate an invite code.");
        } finally {
            setIsInviteUpdating(false);
        }
    };

    const handleRevokeInvite = async () => {
        if (!groupDetail || groupDetail.role !== "owner" || isInviteUpdating) return;
        try {
            setIsInviteUpdating(true);
            setInviteError(null);
            const token = await getToken();
            await revokeGroupInvite(groupId, token);
            setInviteCode(null);
            setInviteStatus({ active: false, created_at: null, use_count: null });
        } catch (err) {
            console.error("Failed to revoke invite:", err);
            setInviteError("Could not revoke the invite code.");
        } finally {
            setIsInviteUpdating(false);
        }
    };

    const handleCopyInvite = async () => {
        if (!inviteCode) return;
        try {
            await navigator.clipboard.writeText(inviteCode);
        } catch (err) {
            console.error("Failed to copy invite code:", err);
            setInviteError("Copy failed. Select the code and copy it manually.");
        }
    };

    const handleUpdateNickname = async (clear = false) => {
        if (!groupDetail || isNicknameUpdating) return;
        const currentMember = groupDetail.members.find(
            (member) => member.id === groupDetail.current_user_id
        );
        try {
            setIsNicknameUpdating(true);
            setNicknameError(null);
            const token = await getToken();
            const member = await updateOwnGroupNickname(
                groupId,
                clear ? null : nicknameDraft,
                token
            );
            setNicknameDraft(member.nickname || "");
            setGroupDetail((detail) => detail && {
                ...detail,
                members: detail.members.map((existing) =>
                    existing.id === member.id ? member : existing
                ),
            });
            if (currentMember) {
                setAvailability((entries) => entries.map((entry) =>
                    entry.user_id === member.id || entry.user_name === currentMember.display_name
                        ? { ...entry, user_name: member.display_name }
                        : entry
                ));
            }
        } catch (err) {
            console.error("Failed to update group nickname:", err);
            setNicknameError("Could not update your name in this group.");
        } finally {
            setIsNicknameUpdating(false);
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
    const selectedDateString = selectedDate ? format(selectedDate, "yyyy-MM-dd") : null;
    const selectedGroupSession = selectedDateString
        ? confirmedSessions.find((session) => session.day === selectedDateString)
        : undefined;
    const selectedOtherGroupSessions = selectedDateString
        ? otherGroupConfirmedSessionsForDay(
            myConfirmedSessions,
            groupId,
            selectedDateString
        )
        : [];

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            {/* Authenticated Top Navigation Shell */}
            <header className="sticky top-0 z-50 border-b border-slate-700/70 bg-[#141c26]/95 shadow-[0_8px_30px_rgba(0,0,0,0.22)] backdrop-blur-xl">
                <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 sm:px-6">
                    <div className="flex items-center gap-4">
                        <Link href="/app" className="flex items-center gap-2.5 group">
                            <div className="flex size-9 items-center justify-center rounded-lg border border-amber-300/35 bg-amber-300/10 text-amber-200 shadow-[0_0_18px_rgba(213,167,91,0.12)] text-lg font-bold transition group-hover:border-amber-300/70">
                                🎲
                            </div>
                            <span className="hidden font-serif text-base font-bold tracking-tight text-stone-100 sm:inline">
                                DnD Planner
                            </span>
                        </Link>

                        <div className="hidden h-6 w-px bg-slate-700 sm:block" />

                        {/* Group Switcher Selector */}
                        <div className="relative">
                            <button
                                onClick={() => setIsGroupDropdownOpen((prev) => !prev)}
                                className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-800/70 px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:border-slate-600 hover:bg-slate-700"
                            >
                                <Users size={14} className="text-amber-200" />
                                <span className="truncate max-w-[150px] sm:max-w-[200px]">
                                    {groupDetail ? groupDetail.name : "Loading..."}
                                </span>
                                <ChevronDown size={14} className="text-slate-500" />
                            </button>

                            {isGroupDropdownOpen && (
                                <>
                                    <div
                                        className="fixed inset-0 z-40"
                                        onClick={() => setIsGroupDropdownOpen(false)}
                                    />
                                    <div className="absolute left-0 z-50 mt-2 w-56 space-y-1 rounded-lg border border-slate-700 bg-[#1a232e] p-1.5 shadow-2xl">
                                        <div className="px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-amber-200/60">
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
                                                        ? "bg-amber-200/10 text-amber-100 font-bold"
                                                        : "text-slate-300 hover:bg-slate-700/70"
                                                )}
                                            >
                                                <span className="truncate">{g.name}</span>
                                                {g.id === groupId && <Check size={14} />}
                                            </button>
                                        ))}
                                        <div className="border-t border-slate-700 pt-1">
                                            <Link
                                                href="/schedule"
                                                className="flex w-full items-center gap-1.5 rounded-md px-3 py-1.5 text-left text-xs font-semibold text-slate-400 transition hover:bg-slate-700/70 hover:text-slate-100"
                                                onClick={() => setIsGroupDropdownOpen(false)}
                                            >
                                                <CalendarDays size={13} />
                                                <span>My Schedule</span>
                                            </Link>
                                            <Link
                                                href="/app"
                                                className="flex w-full items-center gap-1.5 rounded-md px-3 py-1.5 text-left text-xs font-semibold text-slate-400 transition hover:bg-slate-700/70 hover:text-slate-100"
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
                            href="/schedule"
                            className="hidden items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 md:flex"
                        >
                            <CalendarDays size={14} />
                            <span>My Schedule</span>
                        </Link>
                        <Link
                            href="/app"
                            className="hidden items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 md:flex"
                        >
                            <LayoutDashboard size={14} />
                            <span>Dashboard</span>
                        </Link>
                        <div className="h-6 w-px bg-slate-700" />
                        <ThemeToggle />
                        <div className="h-6 w-px bg-slate-700" />
                        <UserButton />
                    </div>
                </div>
            </header>

            {/* Main Content Area */}
            <main className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6">
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
                    <div className="space-y-5">
                        {/* Group Header Banner */}
                        <div className="flex flex-col gap-4 rounded-xl border border-slate-700/80 bg-[#1a232e] p-5 shadow-[0_12px_28px_rgba(0,0,0,0.16)] md:flex-row md:items-center md:justify-between">
                            <div>
                                <div className="flex items-center gap-3 mb-1">
                                    <h1 className="font-serif text-3xl font-bold tracking-tight text-stone-100">{groupDetail.name}</h1>
                                    <span
                                        className={clsx(
                                            "inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded-full",
                                            groupDetail.role === "owner"
                                                ? "border border-amber-200/25 bg-amber-200/10 text-amber-100"
                                                : "bg-slate-700/80 text-slate-300"
                                        )}
                                    >
                                        {groupDetail.role === "owner" && <Crown size={12} />}
                                        {groupDetail.role === "owner" ? "Group Owner" : "Member"}
                                    </span>
                                </div>
                                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-400">
                                    <span>Timezone: <strong className="text-slate-200">{groupDetail.timezone}</strong></span>
                                    <span className="text-amber-200/60">&bull;</span>
                                    <span>Playing as: <strong className="text-amber-100">{currentUserMember?.display_name || "Adventurer"}</strong></span>
                                </div>
                            </div>

                            {/* Month Navigator Controls */}
                            <div className="flex items-center gap-1 self-start rounded-lg border border-slate-700 bg-[#141c26] p-1 md:self-auto">
                                <button
                                    onClick={() => setCurrentDate(subMonths(currentDate, 12))}
                                    className="rounded-md p-1.5 text-xs font-bold text-slate-400 transition hover:bg-slate-700 hover:text-amber-100"
                                    title="Previous Year"
                                >
                                    &laquo;
                                </button>
                                <button
                                    onClick={() => setCurrentDate(subMonths(currentDate, 1))}
                                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-700 hover:text-amber-100"
                                    title="Previous Month"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <span className="min-w-[130px] px-2 text-center text-xs font-bold text-amber-100">
                                    {format(currentDate, "MMMM yyyy")}
                                </span>
                                <button
                                    onClick={() => setCurrentDate(addMonths(currentDate, 1))}
                                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-700 hover:text-amber-100"
                                    title="Next Month"
                                >
                                    <ChevronRight size={16} />
                                </button>
                                <button
                                    onClick={() => setCurrentDate(addMonths(currentDate, 12))}
                                    className="rounded-md p-1.5 text-xs font-bold text-slate-400 transition hover:bg-slate-700 hover:text-amber-100"
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
                                    className="ml-1 rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:bg-slate-700"
                                >
                                    Today
                                </button>
                            </div>
                        </div>

                        {groupDetail.role === "owner" && (
                            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <KeyRound size={17} className="text-blue-600 dark:text-blue-400" />
                                            <h2 className="text-sm font-extrabold">Invite Players</h2>
                                        </div>
                                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                            Invite codes can be reused until you generate a new one or revoke it.
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        {inviteCode ? (
                                            <>
                                                <code className="rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm font-bold tracking-widest text-slate-800 dark:bg-slate-800 dark:text-slate-100">
                                                    {inviteCode}
                                                </code>
                                                <button
                                                    onClick={() => void handleCopyInvite()}
                                                    className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                                                >
                                                    Copy
                                                </button>
                                            </>
                                        ) : inviteStatus?.active ? (
                                            <span className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                                                A code is active. Generate a new code to display and replace it.
                                            </span>
                                        ) : (
                                            <span className="text-xs text-slate-500 dark:text-slate-400">No active join code.</span>
                                        )}
                                        <button
                                            onClick={() => void handleGenerateInvite()}
                                            disabled={isInviteUpdating}
                                            className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                                        >
                                            {inviteStatus?.active ? "Generate new code" : "Generate code"}
                                        </button>
                                        {inviteStatus?.active && (
                                            <button
                                                onClick={() => void handleRevokeInvite()}
                                                disabled={isInviteUpdating}
                                                className="rounded-lg px-3 py-2 text-xs font-bold text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:text-rose-300 dark:hover:bg-rose-950/40"
                                            >
                                                Revoke
                                            </button>
                                        )}
                                    </div>
                                </div>
                                {inviteError && <p className="mt-3 text-xs font-semibold text-rose-600 dark:text-rose-300">{inviteError}</p>}
                            </section>
                        )}

                        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                                <div>
                                    <h2 className="text-sm font-extrabold">Your name in this group</h2>
                                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Leave it empty to use your DnD Planner display name.</p>
                                </div>
                                <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                                    <input
                                        value={nicknameDraft}
                                        onChange={(event) => setNicknameDraft(event.target.value)}
                                        maxLength={120}
                                        placeholder={currentUserMember?.display_name || "Display name"}
                                        className="min-w-56 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                    <button
                                        onClick={() => void handleUpdateNickname()}
                                        disabled={isNicknameUpdating}
                                        className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                                    >
                                        Save
                                    </button>
                                    <button
                                        onClick={() => void handleUpdateNickname(true)}
                                        disabled={isNicknameUpdating || !nicknameDraft}
                                        className="rounded-lg px-3 py-2 text-xs font-bold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-300 dark:hover:bg-slate-800"
                                    >
                                        Clear
                                    </button>
                                </div>
                            </div>
                            {nicknameError && <p className="mt-3 text-xs font-semibold text-rose-600 dark:text-rose-300">{nicknameError}</p>}
                        </section>

                        {/* Interactive Availability Matrix & Calendar */}
                        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
                            {/* Left 2 Cols: Group Availability Calendar Grid */}
                            <div className="rounded-xl border border-slate-700/80 bg-[#1a232e] p-4 shadow-[0_12px_28px_rgba(0,0,0,0.16)] sm:p-5">
                                <div className="flex items-center justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <CalendarDays size={18} className="text-amber-200" />
                                        <h2 className="font-serif text-lg font-bold text-stone-100">Group Calendar</h2>
                                    </div>
                                    <div className="hidden items-center gap-3 text-[10px] text-slate-400 sm:flex">
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

                                <p className="mb-5 text-xs text-slate-400">
                                    Click any date in the calendar below to toggle your own availability (<strong>Available &rarr; Maybe &rarr; No &rarr; Clear</strong>).
                                </p>
                                {availabilityWarning && (
                                    <p className="-mt-3 mb-5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/40 dark:text-amber-200">
                                        {availabilityWarning}
                                    </p>
                                )}

                                {/* Month Days Grid */}
                                <div className="grid grid-cols-7 gap-2 mb-2">
                                    {DAYS.map((day) => (
                                        <div key={day} className="py-1 text-center text-[10px] font-bold text-slate-500">
                                            {day}
                                        </div>
                                    ))}
                                </div>

                                <div className="grid grid-cols-7 gap-2">
                                    {startPadding.map((_, i) => (
                                        <div key={`pad-${i}`} className="min-h-[88px] rounded-md border border-transparent bg-[#141c26]/40" />
                                    ))}

                                    {daysInMonth.map((date) => {
                                        const dateStr = format(date, "yyyy-MM-dd");
                                        const dayEntries = availability.filter((a) => a.date === dateStr);
                                        const availableCount = dayEntries.filter((a) => a.status === "Available").length;
                                        const maybeCount = dayEntries.filter((a) => a.status === "Maybe").length;
                                        const noCount = dayEntries.filter((a) => a.status === "No").length;
                                        const groupSession = confirmedSessions.find(
                                            (session) => session.day === dateStr
                                        );
                                        const otherGroupSessions = otherGroupConfirmedSessionsForDay(
                                            myConfirmedSessions,
                                            groupId,
                                            dateStr
                                        );

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
                                                    "relative flex min-h-[88px] flex-col justify-between rounded-md border p-2 text-left transition sm:min-h-[104px]",
                                                    isSelected
                                                        ? "border-amber-200 bg-amber-200/[0.09] ring-1 ring-amber-200/70"
                                                        : groupSession
                                                            ? "border-amber-300/55 bg-amber-200/[0.05] hover:border-amber-200"
                                                            : "border-slate-700/80 bg-[#151d27] hover:border-slate-600",
                                                    isCurrentDay
                                                        ? "font-bold shadow-[inset_0_0_0_1px_rgba(96,165,250,0.35)]"
                                                        : ""
                                                )}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <span
                                                        className={clsx(
                                                            "flex size-5 items-center justify-center rounded-full text-xs font-bold",
                                                            isCurrentDay
                                                                ? "bg-sky-400 text-slate-950"
                                                                : "text-slate-300"
                                                        )}
                                                    >
                                                        {format(date, "d")}
                                                    </span>

                                                    {ownEntry && (
                                                        <span
                                                            className={clsx(
                                                                "rounded px-1.5 py-0.5 text-[10px] font-extrabold",
                                                                ownEntry.status === "Available" && "bg-emerald-400/15 text-emerald-200",
                                                                ownEntry.status === "Maybe" && "bg-amber-300/15 text-amber-100",
                                                                ownEntry.status === "No" && "bg-rose-400/15 text-rose-200"
                                                            )}
                                                        >
                                                            {ownEntry.status === "Available" ? "✓" : ownEntry.status === "Maybe" ? "?" : "✗"}
                                                        </span>
                                                    )}
                                                </div>

                                                {/* Group counts badge */}
                                                <div className="space-y-1 mt-1">
                                                    {groupSession && (
                                                        <div className="rounded bg-amber-200/14 px-1.5 py-0.5 text-[9px] font-bold text-amber-100 sm:text-[10px]">
                                                            ✓ Confirmed session
                                                        </div>
                                                    )}
                                                    {otherGroupSessions.map((session) => (
                                                        <div
                                                            key={session.id}
                                                            className="truncate rounded bg-sky-400/12 px-1.5 py-0.5 text-[9px] font-semibold text-sky-200 sm:text-[10px]"
                                                            title={`Session : ${session.group_name}`}
                                                        >
                                                            Session : {session.group_name}
                                                        </div>
                                                    ))}
                                                    {availableCount > 0 && (
                                                        <div className="flex items-center gap-1 text-[10px] font-semibold text-emerald-300">
                                                            <span>🟢</span> {availableCount}/{groupDetail.members.length}
                                                        </div>
                                                    )}
                                                    {maybeCount > 0 && availableCount === 0 && (
                                                        <div className="flex items-center gap-1 text-[10px] font-semibold text-amber-200">
                                                            <span>🟡</span> {maybeCount} maybe
                                                        </div>
                                                    )}
                                                    {availableCount === 0 && maybeCount === 0 && noCount > 0 && (
                                                        <div className="text-[10px] font-semibold text-slate-500">
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
                            <div className="space-y-5">
                                <div className="relative overflow-hidden rounded-xl border border-slate-700/80 bg-[#18212c] p-5 shadow-[0_12px_28px_rgba(0,0,0,0.16)]">
                                    <div className="pointer-events-none absolute -right-10 -top-9 flex size-36 items-center justify-center rounded-full border border-amber-200/10 text-5xl text-amber-200/[0.06]">✦</div>
                                    <div className="relative mb-4 flex items-center justify-between">
                                        <h3 className="font-serif text-lg font-bold text-stone-100">
                                            {selectedDate ? format(selectedDate, "EEEE, MMMM d") : "Select a day"}
                                        </h3>
                                        {selectedDate && (
                                            <button
                                                onClick={() => void handleToggleOwnAvailability(selectedDate)}
                                                className="cursor-pointer rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-xs font-semibold text-slate-200 transition hover:border-amber-200/45 hover:text-amber-100"
                                            >
                                                Toggle My Status
                                            </button>
                                        )}
                                    </div>

                                    {selectedDate && (
                                        <div className="mb-4 space-y-2">
                                            {selectedGroupSession && (
                                                <div className="rounded-md border border-amber-200/25 bg-amber-200/[0.09] px-3 py-2 text-xs font-bold text-amber-100">
                                                    ✓ Confirmed session for {groupDetail.name}
                                                </div>
                                            )}
                                            {selectedOtherGroupSessions.map((session) => (
                                                <div
                                                    key={session.id}
                                                    className="rounded-md border border-sky-400/20 bg-sky-400/[0.08] px-3 py-2 text-xs font-semibold text-sky-100"
                                                >
                                                    Session : {session.group_name}
                                                </div>
                                            ))}
                                            {groupDetail.role === "owner" && (
                                                <button
                                                    onClick={() => void handleToggleConfirmation(selectedDate)}
                                                    disabled={isConfirmationUpdating}
                                                    className={clsx(
                                                        "w-full rounded-lg px-3 py-2 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-60",
                                                        selectedGroupSession
                                                            ? "border border-rose-400/30 bg-rose-400/10 text-rose-200 hover:bg-rose-400/15"
                                                            : "bg-[#d5a75b] text-[#18140f] hover:bg-[#e4bc77]"
                                                    )}
                                                >
                                                    {selectedGroupSession
                                                        ? "Cancel confirmation"
                                                        : "Confirm session"}
                                                </button>
                                            )}
                                        </div>
                                    )}

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
                                                            "flex items-center justify-between rounded-md border p-2.5 text-xs transition",
                                                            isSelf
                                                                ? "border-amber-200/35 bg-amber-200/[0.07] font-semibold"
                                                                : "border-slate-700/70 bg-[#141c26]/70"
                                                        )}
                                                    >
                                                        <div className="flex items-center gap-2.5">
                                                            <div className="flex size-7 items-center justify-center rounded-md bg-slate-700 font-bold text-[10px] text-slate-200">
                                                                {member.display_name.slice(0, 2).toUpperCase()}
                                                            </div>
                                                            <div>
                                                                <span className="font-medium text-slate-100">
                                                                    {member.display_name} {isSelf && <span className="text-[10px] text-amber-200">(You)</span>}
                                                                </span>
                                                                {member.role === "owner" && (
                                                                    <span className="ml-1.5 text-[10px] font-bold text-amber-200">DM</span>
                                                                )}
                                                            </div>
                                                        </div>

                                                        <div>
                                                            {memberEntry?.status === "Available" ? (
                                                                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-400/15 px-2 py-0.5 font-bold text-emerald-200">
                                                                    <Check size={12} /> Available
                                                                </span>
                                                            ) : memberEntry?.status === "Maybe" ? (
                                                                <span className="inline-flex items-center gap-1 rounded-full bg-amber-300/15 px-2 py-0.5 font-bold text-amber-100">
                                                                    <HelpCircle size={12} /> Maybe
                                                                </span>
                                                            ) : memberEntry?.status === "No" ? (
                                                                <span className="inline-flex items-center gap-1 rounded-full bg-rose-400/15 px-2 py-0.5 font-bold text-rose-200">
                                                                    <X size={12} /> No
                                                                </span>
                                                            ) : (
                                                                <span className="text-[11px] text-slate-500">Unset</span>
                                                            )}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>

                                {/* Group Members Card */}
                                <div className="rounded-xl border border-slate-700/80 bg-[#18212c] p-5 shadow-[0_12px_28px_rgba(0,0,0,0.16)]">
                                    <h3 className="mb-3 flex items-center gap-2 font-serif text-base font-bold text-stone-100">
                                        <Users size={16} className="text-amber-200/70" />
                                        <span>Roster ({groupDetail.members.length})</span>
                                    </h3>
                                    <div className="flex flex-wrap gap-2">
                                        {groupDetail.members.map((m) => (
                                            <span
                                                key={m.id}
                                                className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800/70 px-2.5 py-1 text-xs text-slate-300"
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
