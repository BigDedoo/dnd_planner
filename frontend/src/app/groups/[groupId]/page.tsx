"use client";

import { useEffect, useMemo, useRef, useState, use } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import {
    fetchGroupDetail,
    fetchGroupMonthAvailability,
    fetchGroupConfirmedSessions,
    fetchMyConfirmedSessions,
    fetchMyGroups,
    confirmGroupSession,
    cancelGroupSession,
    updateGroupSession,
    updateOwnSessionRsvp,
    fetchGroupInviteStatus,
    generateGroupInvite,
    revokeGroupInvite,
    fetchOnboardingStatus,
    updateGroupAvailability,
    updateOwnGroupNickname,
    downloadGroupSessionIcs,
    ConfirmedSession,
    GroupDetail,
    Availability,
    MyConfirmedSession,
    MyGroup,
    GroupInviteStatus,
    SessionRsvpStatus,
} from "@/services/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import { otherGroupConfirmedSessionsForDay } from "@/lib/confirmedSessions";
import { bestDateReason, rankBestDates } from "@/lib/bestDates";
import { googleCalendarUrl } from "@/lib/calendarExport";
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
    parseISO,
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
    Clock3,
    HelpCircle,
    KeyRound,
    Settings2,
    X,
    Download,
    RotateCcw,
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
    const searchParams = useSearchParams();

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
    const [sessionTitle, setSessionTitle] = useState("");
    const [sessionStartTime, setSessionStartTime] = useState("19:00");
    const [sessionDuration, setSessionDuration] = useState("240");
    const [sessionNotes, setSessionNotes] = useState("");
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
    const [isNicknameEditing, setIsNicknameEditing] = useState(false);
    const [availabilityMessage, setAvailabilityMessage] = useState<string | null>(null);
    const [failedAvailabilityChange, setFailedAvailabilityChange] = useState<{ day: string; status: string | null } | null>(null);
    const [lastAvailabilityChange, setLastAvailabilityChange] = useState<{ day: string; previous: string | null; next: string | null } | null>(null);
    const [isBestDatesOpen, setIsBestDatesOpen] = useState(false);
    const bestDatesPopoverRef = useRef<HTMLDivElement>(null);
    const bestDatesButtonRef = useRef<HTMLButtonElement>(null);
    const bestDatesCloseRef = useRef<HTMLButtonElement>(null);

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
        const requestedDay = searchParams.get("day");
        if (!requestedDay || !/^\d{4}-\d{2}-\d{2}$/.test(requestedDay)) return;
        const requestedDate = parseISO(requestedDay);
        setCurrentDate(requestedDate);
        setSelectedDate(requestedDate);
    }, [searchParams]);

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

    const setOwnAvailability = async (
        targetDate: Date,
        nextStatus: string | null,
        rememberForUndo = true
    ) => {
        if (!groupDetail || isUpdating) return false;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const currentUserMember = groupDetail.members.find(
            (m) => m.id === groupDetail.current_user_id
        );
        const currentUserName = currentUserMember?.display_name || "Me";
        const currentEntry = availability.find(
            (a) => a.date === dateStr && (a.user_id === groupDetail.current_user_id || a.user_name === currentUserName)
        );
        const previousStatus = currentEntry?.status || null;
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
        setAvailabilityMessage(null);
        setFailedAvailabilityChange(null);
        const optimistic = availability.filter(
            (a) => !(a.date === dateStr && (a.user_id === groupDetail.current_user_id || a.user_name === currentUserName))
        );
        if (nextStatus) {
            optimistic.push({
                group_name: groupDetail.name,
                user_name: currentUserName,
                user_id: groupDetail.current_user_id,
                date: dateStr,
                status: nextStatus,
            });
        }
        setAvailability(optimistic);

        try {
            setIsUpdating(true);
            const token = await getToken();
            await updateGroupAvailability(groupId, dateStr, nextStatus, token);
            if (rememberForUndo) {
                setLastAvailabilityChange({ day: dateStr, previous: previousStatus, next: nextStatus });
            }
            return true;
        } catch (err) {
            console.error("Failed to update availability:", err);
            setAvailability(availability);
            setFailedAvailabilityChange({ day: dateStr, status: nextStatus });
            setAvailabilityMessage("Your availability was not saved. The calendar was restored.");
            return false;
        } finally {
            setIsUpdating(false);
        }
    };

    // 3. Handle Current User Availability Cycling
    const handleToggleOwnAvailability = async (targetDate: Date) => {
        if (!groupDetail || isUpdating) return;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const currentEntry = availability.find(
            (entry) => entry.date === dateStr && entry.user_id === groupDetail.current_user_id
        );
        let nextStatus: string | null = "Available";
        if (currentEntry?.status === "Available") nextStatus = "Maybe";
        else if (currentEntry?.status === "Maybe") nextStatus = "No";
        else if (currentEntry?.status === "No") nextStatus = null;
        await setOwnAvailability(targetDate, nextStatus);
    };

    const handleUndoAvailability = async () => {
        if (!lastAvailabilityChange) return;
        const change = lastAvailabilityChange;
        const restored = await setOwnAvailability(parseISO(change.day), change.previous, false);
        if (restored) {
            setLastAvailabilityChange(null);
            setAvailabilityMessage("Last availability change undone.");
        }
    };

    const handleRetryAvailability = async () => {
        if (!failedAvailabilityChange) return;
        await setOwnAvailability(parseISO(failedAvailabilityChange.day), failedAvailabilityChange.status);
    };

    const replaceSession = (updated: ConfirmedSession) => {
        setConfirmedSessions((sessions) => {
            const existing = sessions.some((session) => session.id === updated.id);
            return existing
                ? sessions.map((session) => (session.id === updated.id ? updated : session))
                : [...sessions, updated];
        });
        setMyConfirmedSessions((sessions) => {
            const personal = { ...updated, group_name: groupDetail?.name || "This group" };
            const existing = sessions.some((session) => session.id === updated.id);
            return existing
                ? sessions.map((session) => (session.id === updated.id ? personal : session))
                : [...sessions, personal];
        });
    };

    const handleSaveSession = async (targetDate: Date) => {
        if (
            !groupDetail ||
            !["owner", "organizer"].includes(groupDetail.role) ||
            isConfirmationUpdating
        ) return;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const existing = confirmedSessions.find((session) => session.day === dateStr);
        try {
            setIsConfirmationUpdating(true);
            const token = await getToken();
            const details = {
                title: sessionTitle || null,
                start_time: sessionStartTime || null,
                duration_minutes: sessionStartTime ? Number(sessionDuration) : null,
                notes: sessionNotes || null,
            };
            const updated = existing
                ? await updateGroupSession(groupId, dateStr, details, token)
                : await confirmGroupSession(groupId, dateStr, details, token);
            replaceSession(updated);
        } catch (err) {
            console.error("Failed to save session:", err);
            setError("Could not save the scheduled session.");
        } finally {
            setIsConfirmationUpdating(false);
        }
    };

    const handleCancelSession = async (targetDate: Date) => {
        if (!groupDetail || !["owner", "organizer"].includes(groupDetail.role) || isConfirmationUpdating) return;
        const dateStr = format(targetDate, "yyyy-MM-dd");
        const existing = confirmedSessions.find((session) => session.day === dateStr);
        if (!existing || !window.confirm("Cancel this scheduled session?")) return;
        try {
            setIsConfirmationUpdating(true);
            const token = await getToken();
            await cancelGroupSession(groupId, dateStr, token);
            setConfirmedSessions((sessions) => sessions.filter((session) => session.id !== existing.id));
            setMyConfirmedSessions((sessions) => sessions.filter((session) => session.id !== existing.id));
        } catch (err) {
            console.error("Failed to cancel session:", err);
            setError("Could not cancel the scheduled session.");
        } finally {
            setIsConfirmationUpdating(false);
        }
    };

    const handleRsvp = async (targetDate: Date, status: SessionRsvpStatus) => {
        if (isConfirmationUpdating) return;
        try {
            setIsConfirmationUpdating(true);
            const token = await getToken();
            const updated = await updateOwnSessionRsvp(
                groupId,
                format(targetDate, "yyyy-MM-dd"),
                status,
                token
            );
            replaceSession(updated);
        } catch (err) {
            console.error("Failed to update RSVP:", err);
            setError("Could not update your RSVP.");
        } finally {
            setIsConfirmationUpdating(false);
        }
    };

    const handleDownloadSession = async (confirmedSession: ConfirmedSession) => {
        try {
            const token = await getToken();
            await downloadGroupSessionIcs(groupId, confirmedSession.day, token);
        } catch (err) {
            console.error("Failed to export session:", err);
            setError("Could not download this calendar event.");
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

    const handleCopyInviteCode = async () => {
        if (!inviteCode) return;
        try {
            await navigator.clipboard.writeText(inviteCode);
        } catch (err) {
            console.error("Failed to copy invite code:", err);
            setInviteError("Copy failed. Select the code and copy it manually.");
        }
    };

    const handleCopyInviteLink = async () => {
        if (!inviteCode) return;
        try {
            await navigator.clipboard.writeText(`${window.location.origin}/join/${encodeURIComponent(inviteCode)}`);
        } catch (err) {
            console.error("Failed to copy invite link:", err);
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
            setIsNicknameEditing(false);
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

    useEffect(() => {
        setSessionTitle(selectedGroupSession?.title || "");
        setSessionStartTime(selectedGroupSession?.start_time?.slice(0, 5) || "19:00");
        setSessionDuration(String(selectedGroupSession?.duration_minutes || 240));
        setSessionNotes(selectedGroupSession?.notes || "");
    }, [selectedDateString, selectedGroupSession]);

    const canManageSessions = groupDetail?.role === "owner" || groupDetail?.role === "organizer";
    const bestDates = useMemo(() => {
        const now = new Date();
        const firstUsefulDay = now > monthStart ? now : monthStart;
        return rankBestDates(
            availability,
            groupDetail?.members.length || 0,
            format(firstUsefulDay, "yyyy-MM-dd")
        );
    }, [availability, groupDetail?.members.length, monthStart]);

    useEffect(() => {
        if (!isBestDatesOpen) return;

        const handlePointerDown = (event: PointerEvent) => {
            if (
                bestDatesPopoverRef.current &&
                !bestDatesPopoverRef.current.contains(event.target as Node) &&
                !bestDatesButtonRef.current?.contains(event.target as Node)
            ) {
                setIsBestDatesOpen(false);
            }
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                setIsBestDatesOpen(false);
            }
        };

        document.addEventListener("pointerdown", handlePointerDown);
        document.addEventListener("keydown", handleKeyDown);
        bestDatesCloseRef.current?.focus();
        return () => {
            document.removeEventListener("pointerdown", handlePointerDown);
            document.removeEventListener("keydown", handleKeyDown);
        };
    }, [isBestDatesOpen]);

    const selectBestDate = (day: string) => {
        setSelectedDate(parseISO(day));
        setIsBestDatesOpen(false);
    };

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
                        <Link
                            href={`/groups/${groupId}/sessions`}
                            className="hidden items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 md:flex"
                        >
                            <Clock3 size={14} />
                            <span>Sessions</span>
                        </Link>
                        <Link
                            href={`/groups/${groupId}/settings`}
                            className="hidden items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700/60 hover:text-amber-100 md:flex"
                        >
                            <Settings2 size={14} />
                            <span>Settings</span>
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
                                                    onClick={() => void handleCopyInviteLink()}
                                                    className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700"
                                                >
                                                    Copy invite link
                                                </button>
                                                <button
                                                    onClick={() => void handleCopyInviteCode()}
                                                    className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                                                >
                                                    Copy code
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

                        {/* Interactive Availability Matrix & Calendar */}
                        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
                            {/* Left 2 Cols: Group Availability Calendar Grid */}
                            <div className="relative rounded-xl border border-slate-700/80 bg-[#1a232e] p-4 shadow-[0_12px_28px_rgba(0,0,0,0.16)] sm:p-5">
                                <div className="relative flex items-center justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <CalendarDays size={18} className="text-amber-200" />
                                        <h2 className="font-serif text-lg font-bold text-stone-100">Group Calendar</h2>
                                    </div>
                                    <div className="flex items-center gap-2 sm:gap-3">
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
                                        <button
                                            ref={bestDatesButtonRef}
                                            type="button"
                                            aria-expanded={isBestDatesOpen}
                                            aria-controls="best-dates-popover"
                                            onClick={() => setIsBestDatesOpen((open) => !open)}
                                            className="rounded-md border border-amber-200/30 bg-amber-200/10 px-2.5 py-1.5 text-[11px] font-bold text-amber-100 transition hover:bg-amber-200/15 focus:outline-none focus:ring-2 focus:ring-amber-200/60"
                                        >
                                            Best dates
                                        </button>
                                    </div>
                                </div>

                                {isBestDatesOpen && (
                                    <div
                                        ref={bestDatesPopoverRef}
                                        id="best-dates-popover"
                                        role="dialog"
                                        aria-labelledby="best-dates-title"
                                        className="absolute right-4 top-[4.25rem] z-40 w-[min(19rem,calc(100%-2rem))] rounded-lg border border-amber-200/25 bg-[#141c26] p-3 shadow-[0_18px_40px_rgba(0,0,0,0.4)] sm:right-5"
                                    >
                                        <div className="mb-2 flex items-center justify-between gap-3">
                                            <h3 id="best-dates-title" className="text-xs font-bold text-amber-100">Best dates</h3>
                                            <button
                                                ref={bestDatesCloseRef}
                                                type="button"
                                                aria-label="Close Best dates"
                                                onClick={() => setIsBestDatesOpen(false)}
                                                className="rounded p-1 text-slate-400 transition hover:bg-slate-700/70 hover:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-200/60"
                                            >
                                                <X size={14} />
                                            </button>
                                        </div>
                                        {bestDates.length === 0 ? (
                                            <p className="text-xs text-slate-500">Add upcoming availability to see recommendations.</p>
                                        ) : (
                                            <div className="space-y-1">
                                                {bestDates.map((recommendation) => (
                                                    <button
                                                        key={recommendation.day}
                                                        type="button"
                                                        onClick={() => selectBestDate(recommendation.day)}
                                                        className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-xs transition hover:bg-amber-200/10 focus:outline-none focus:ring-2 focus:ring-amber-200/60"
                                                    >
                                                        <span className="font-bold text-slate-200">{format(parseISO(recommendation.day), "EEE d MMM")}</span>
                                                        <span className="text-right text-[11px] text-slate-400">{bestDateReason(recommendation, groupDetail.members.length)}</span>
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}

                                <p className="mb-5 text-xs text-slate-400">
                                    Click any date in the calendar below to toggle your own availability (<strong>Available &rarr; Maybe &rarr; No &rarr; Clear</strong>).
                                </p>
                                {availabilityWarning && (
                                    <p className="-mt-3 mb-5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/40 dark:text-amber-200">
                                        {availabilityWarning}
                                    </p>
                                )}

                                {(availabilityMessage || isUpdating || lastAvailabilityChange || failedAvailabilityChange) && <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-[11px] text-slate-400"><span>{isUpdating ? "Saving availability…" : availabilityMessage || "Availability saved."}</span>{lastAvailabilityChange && !isUpdating && <button onClick={() => void handleUndoAvailability()} className="inline-flex items-center gap-1 font-bold text-amber-200"><RotateCcw size={11} /> Undo</button>}{failedAvailabilityChange && !isUpdating && <button onClick={() => void handleRetryAvailability()} className="font-bold text-rose-200">Retry</button>}</div>}

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
                                                            ✓ {groupSession.start_time ? groupSession.start_time.slice(0, 5) : "Session"}
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
                                                Cycle day status
                                            </button>
                                        )}
                                    </div>

                                    {selectedDate && (
                                        <div className="mb-4 space-y-2">
                                            <div className="rounded-lg border border-slate-700 bg-[#141c26]/70 p-3">
                                                <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Your day availability</p>
                                                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 xl:grid-cols-2">{(["Available", "Maybe", "No", null] as const).map((status) => <button key={status || "clear"} disabled={isUpdating} onClick={() => void setOwnAvailability(selectedDate, status)} className="rounded-md bg-slate-800 px-2 py-1.5 text-[10px] font-bold text-slate-300 transition hover:text-amber-100 disabled:opacity-50">{status === "No" ? "Unavailable" : status || "Clear"}</button>)}</div>
                                                <p className="mt-2 text-[10px] text-slate-500">Availability means whether you could play that day. Session RSVP is set separately below.</p>
                                            </div>
                                            {selectedGroupSession && (
                                                <div className="rounded-md border border-amber-200/25 bg-amber-200/[0.09] px-3 py-2 text-xs text-amber-100">
                                                    <p className="font-bold">✓ {selectedGroupSession.title || `Session for ${groupDetail.name}`}</p>
                                                    {selectedGroupSession.start_time && (
                                                        <p className="mt-1 flex items-center gap-1 text-[11px] text-amber-100/80"><Clock3 size={12} /> {selectedGroupSession.start_time.slice(0, 5)} · {selectedGroupSession.duration_minutes} min</p>
                                                    )}
                                                    {selectedGroupSession.notes && <p className="mt-1 text-[11px] font-normal text-slate-300">{selectedGroupSession.notes}</p>}
                                                    <div className="mt-2 flex flex-wrap gap-2"><button onClick={() => void handleDownloadSession(selectedGroupSession)} className="inline-flex items-center gap-1 rounded bg-slate-900/40 px-2 py-1 text-[10px] font-bold text-amber-100"><Download size={11} /> Download ICS</button><a href={googleCalendarUrl(selectedGroupSession, groupDetail.name)} target="_blank" rel="noreferrer" className="rounded bg-slate-900/40 px-2 py-1 text-[10px] font-bold text-amber-100">Add to Google Calendar</a><Link href={`/groups/${groupId}/sessions`} className="rounded bg-slate-900/40 px-2 py-1 text-[10px] font-bold text-amber-100">All sessions</Link></div>
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
                                            {canManageSessions && (
                                                <div className="space-y-2 rounded-lg border border-slate-700 bg-[#141c26]/70 p-3">
                                                    <p className="text-[10px] font-bold uppercase tracking-wider text-amber-200/70">{selectedGroupSession ? "Edit scheduled session" : "Schedule a session"}</p>
                                                    <input value={sessionTitle} onChange={(event) => setSessionTitle(event.target.value)} placeholder="Title (optional)" maxLength={120} className="w-full rounded-md border border-slate-600 bg-slate-800 px-2.5 py-2 text-xs text-slate-100 placeholder:text-slate-500" />
                                                    <div className="grid grid-cols-2 gap-2">
                                                        <input type="time" value={sessionStartTime} onChange={(event) => setSessionStartTime(event.target.value)} className="rounded-md border border-slate-600 bg-slate-800 px-2.5 py-2 text-xs text-slate-100" />
                                                        <input type="number" min="15" max="1440" step="15" value={sessionDuration} onChange={(event) => setSessionDuration(event.target.value)} aria-label="Duration in minutes" className="rounded-md border border-slate-600 bg-slate-800 px-2.5 py-2 text-xs text-slate-100" />
                                                    </div>
                                                    <textarea value={sessionNotes} onChange={(event) => setSessionNotes(event.target.value)} placeholder="Notes (optional)" maxLength={4000} rows={2} className="w-full resize-y rounded-md border border-slate-600 bg-slate-800 px-2.5 py-2 text-xs text-slate-100 placeholder:text-slate-500" />
                                                    <button onClick={() => void handleSaveSession(selectedDate)} disabled={isConfirmationUpdating} className="w-full rounded-lg bg-[#d5a75b] px-3 py-2 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60">{selectedGroupSession ? "Save session details" : "Confirm session"}</button>
                                                    {selectedGroupSession && <button onClick={() => void handleCancelSession(selectedDate)} disabled={isConfirmationUpdating} className="w-full rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-200 transition hover:bg-rose-400/15 disabled:opacity-60">Cancel session</button>}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {selectedDate && (
                                        selectedGroupSession && (
                                            <div className="mb-4 rounded-lg border border-slate-700 bg-[#141c26]/70 p-3">
                                                <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">RSVP roster</p>
                                                <div className="space-y-1.5">
                                                    {groupDetail.members.map((member) => {
                                                        const response = selectedGroupSession.rsvps?.find((rsvp) => rsvp.user_id === member.id);
                                                        const isSelf = member.id === groupDetail.current_user_id;
                                                        const label = response?.status === "going" ? "Going" : response?.status === "maybe" ? "Maybe" : response?.status === "declined" ? "Declined" : "No RSVP";
                                                        return <div key={member.id} className="flex items-center justify-between gap-2 text-xs"><span className="truncate text-slate-300">{member.display_name}{isSelf && " (You)"}</span>{isSelf ? <div className="flex gap-1">{(["going", "maybe", "declined"] as SessionRsvpStatus[]).map((status) => <button key={status} disabled={isConfirmationUpdating} onClick={() => void handleRsvp(selectedDate, status)} className={clsx("rounded px-1.5 py-1 text-[10px] font-bold", response?.status === status ? "bg-amber-200/20 text-amber-100" : "bg-slate-800 text-slate-400 hover:text-slate-100")}>{status === "going" ? "Going" : status === "maybe" ? "Maybe" : "No"}</button>)}</div> : <span className={clsx("rounded px-1.5 py-1 text-[10px] font-bold", response?.status === "going" && "bg-emerald-400/15 text-emerald-200", response?.status === "maybe" && "bg-amber-300/15 text-amber-100", response?.status === "declined" && "bg-rose-400/15 text-rose-200", !response && "bg-slate-800 text-slate-500")}>{label}</span>}</div>;
                                                    })}
                                                </div>
                                            </div>
                                        )
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
                                    <div className="mt-4 border-t border-slate-700/70 pt-3">
                                        <div className="flex items-center justify-between gap-3">
                                            <div className="min-w-0">
                                                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Your name in this group</p>
                                                <p className="mt-1 truncate text-xs font-semibold text-slate-200">
                                                    {currentUserMember?.nickname?.trim() || currentUserMember?.display_name || "Your display name"}
                                                </p>
                                            </div>
                                            <button
                                                onClick={() => {
                                                    setNicknameDraft(currentUserMember?.nickname || "");
                                                    setNicknameError(null);
                                                    setIsNicknameEditing((editing) => !editing);
                                                }}
                                                className="shrink-0 text-xs font-bold text-amber-200 transition hover:text-amber-100"
                                            >
                                                {isNicknameEditing ? "Close" : "Edit"}
                                            </button>
                                        </div>
                                        {isNicknameEditing && (
                                            <div className="mt-3 space-y-2">
                                                <input
                                                    value={nicknameDraft}
                                                    onChange={(event) => setNicknameDraft(event.target.value)}
                                                    maxLength={120}
                                                    placeholder={currentUserMember?.display_name || "Display name"}
                                                    className="w-full rounded-md border border-slate-600 bg-[#141c26] px-2.5 py-2 text-xs text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-amber-200/60"
                                                />
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <button
                                                        onClick={() => void handleUpdateNickname()}
                                                        disabled={isNicknameUpdating}
                                                        className="rounded-md bg-[#d5a75b] px-3 py-1.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60"
                                                    >
                                                        Save
                                                    </button>
                                                    <button
                                                        onClick={() => void handleUpdateNickname(true)}
                                                        disabled={isNicknameUpdating || !nicknameDraft}
                                                        className="rounded-md px-2 py-1.5 text-xs font-semibold text-slate-400 transition hover:bg-slate-800 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                                                    >
                                                        Clear
                                                    </button>
                                                    <span className="text-[10px] text-slate-500">Leave blank to use your display name.</span>
                                                </div>
                                                {nicknameError && <p className="text-xs font-semibold text-rose-300">{nicknameError}</p>}
                                            </div>
                                        )}
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
