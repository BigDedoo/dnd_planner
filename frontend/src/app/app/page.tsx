"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
    createGroup,
    fetchMyConfirmedSessions,
    fetchMyGroups,
    fetchOnboardingStatus,
    joinGroupWithCode,
    MyConfirmedSession,
    MyGroup,
} from "@/services/api";
import { AppHeader, SurfacePanel } from "@/components/AppShell";
import { formatInviteCodeInput } from "@/lib/inviteCode";
import { nextUpcomingConfirmedSession } from "@/lib/mySchedule";
import { ArrowRight, Calendar, Crown, KeyRound, Plus, Shield, Users, X } from "lucide-react";
import clsx from "clsx";
import { format } from "date-fns";

export default function AppDashboard() {
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const [groups, setGroups] = useState<MyGroup[]>([]);
    const [nextSession, setNextSession] = useState<MyConfirmedSession | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [isJoinOpen, setIsJoinOpen] = useState(false);
    const [groupName, setGroupName] = useState("");
    const [groupDescription, setGroupDescription] = useState("");
    const [groupNickname, setGroupNickname] = useState("");
    const [joinCode, setJoinCode] = useState("");
    const [joinNickname, setJoinNickname] = useState("");
    const [formError, setFormError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        let active = true;
        const loadGroups = async () => {
            if (!isLoaded) return;
            try {
                setIsLoading(true);
                const token = await getToken();
                const onboarding = await fetchOnboardingStatus(token);
                if (!onboarding.linked) {
                    router.replace("/onboarding?next=/app");
                    return;
                }
                const today = format(new Date(), "yyyy-MM-dd");
                const [userGroups, confirmedSessions] = await Promise.all([
                    fetchMyGroups(token),
                    fetchMyConfirmedSessions(today, "9999-12-31", token),
                ]);
                if (active) {
                    setGroups(userGroups);
                    setNextSession(nextUpcomingConfirmedSession(confirmedSessions, today));
                    setError(null);
                }
            } catch (err) {
                if (active) {
                    console.error("Failed to load user groups:", err);
                    setError("Failed to load your groups. Please try refreshing.");
                }
            } finally {
                if (active) {
                    setIsLoading(false);
                }
            }
        };

        void loadGroups();
        return () => {
            active = false;
        };
    }, [isLoaded, getToken, router]);

    const closeCreate = () => {
        setIsCreateOpen(false);
        setGroupName("");
        setGroupDescription("");
        setGroupNickname("");
        setFormError(null);
    };

    const closeJoin = () => {
        setIsJoinOpen(false);
        setJoinCode("");
        setJoinNickname("");
        setFormError(null);
    };

    const handleCreateGroup = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!groupName.trim()) {
            setFormError("A group name is required.");
            return;
        }
        try {
            setIsSubmitting(true);
            setFormError(null);
            const token = await getToken();
            const group = await createGroup(
                {
                    name: groupName,
                    description: groupDescription || undefined,
                    nickname: groupNickname || undefined,
                },
                token
            );
            closeCreate();
            router.push(`/groups/${group.id}`);
        } catch (err) {
            setFormError(err instanceof Error ? err.message : "Could not create group.");
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleJoinGroup = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        try {
            setIsSubmitting(true);
            setFormError(null);
            const token = await getToken();
            const group = await joinGroupWithCode(joinCode, joinNickname || undefined, token);
            closeJoin();
            router.push(`/groups/${group.id}`);
        } catch (err) {
            setFormError(err instanceof Error ? err.message : "Could not join group.");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <AppHeader />

            {/* Dashboard Content */}
            <main className="mx-auto w-full max-w-[1320px] px-4 py-7 sm:px-6">
                <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/70">Campaign ledger</p>
                        <h1 className="mt-1 font-serif text-3xl font-bold tracking-tight text-stone-100">My Groups</h1>
                        <p className="mt-1 text-xs text-slate-400">Campaign workspaces where your profile has active membership.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <Link
                            href="/schedule"
                            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-800/70 px-3 py-2 text-xs font-bold text-slate-200 transition hover:border-slate-500 hover:bg-slate-700"
                        >
                            <Calendar size={15} /> My Schedule
                        </Link>
                        <button
                            onClick={() => { setFormError(null); setIsCreateOpen(true); }}
                            className="inline-flex items-center gap-2 rounded-md bg-[#d5a75b] px-3 py-2 text-xs font-bold text-[#18140f] shadow-[0_5px_16px_rgba(213,167,91,0.16)] transition hover:bg-[#e4bc77]"
                        >
                            <Plus size={15} /> Create group
                        </button>
                        <button
                            onClick={() => { setFormError(null); setIsJoinOpen(true); }}
                            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-800/70 px-3 py-2 text-xs font-bold text-slate-200 transition hover:border-slate-500 hover:bg-slate-700"
                        >
                            <KeyRound size={15} /> Join with code
                        </button>
                    </div>
                </div>

                {error && (
                    <div className="mb-6 p-4 rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-sm">
                        {error}
                    </div>
                )}

                {!isLoading && !error && (
                    <SurfacePanel className="mb-7 relative overflow-hidden border-amber-200/20 bg-[linear-gradient(100deg,rgba(213,167,91,0.12),rgba(26,35,46,0.92)_48%)] p-5">
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/75">Next session</p>
                                {nextSession ? (
                                    <>
                                        <p className="mt-1 font-serif text-xl font-bold text-stone-100">{nextSession.group_name}</p>
                                        <p className="text-xs text-slate-400">{format(new Date(`${nextSession.day}T00:00:00`), "EEEE d MMMM")}</p>
                                    </>
                                ) : (
                                    <p className="mt-1 text-xs text-slate-400">No upcoming confirmed sessions.</p>
                                )}
                            </div>
                            <Link
                                href="/schedule"
                                className="inline-flex w-fit items-center gap-2 rounded-md border border-amber-200/35 bg-amber-200/10 px-3 py-2 text-xs font-bold text-amber-100 transition hover:bg-amber-200/20"
                            >
                                View My Schedule <ArrowRight size={14} />
                            </Link>
                        </div>
                    </SurfacePanel>
                )}

                {isLoading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {[1, 2, 3].map((i) => (
                            <div
                                key={i}
                                className="h-44 rounded-xl border border-slate-700 bg-[#1a232e] p-6 animate-pulse"
                            >
                                <div className="h-5 bg-slate-200 dark:bg-slate-800 rounded w-1/2 mb-4" />
                                <div className="h-4 bg-slate-100 dark:bg-slate-800/60 rounded w-1/3 mb-8" />
                                <div className="h-4 bg-slate-100 dark:bg-slate-800/60 rounded w-2/3" />
                            </div>
                        ))}
                    </div>
                ) : groups.length === 0 ? (
                    <div className="mx-auto my-12 max-w-xl rounded-xl border border-dashed border-slate-600 bg-[#1a232e] p-12 text-center">
                        <div className="size-16 rounded-2xl bg-blue-50 dark:bg-blue-950/60 border border-blue-100 dark:border-blue-900/50 flex items-center justify-center text-blue-600 dark:text-blue-400 mx-auto mb-4">
                            <Shield size={32} />
                        </div>
                        <h2 className="mb-2 font-serif text-xl font-bold text-stone-100">You don&apos;t belong to any groups yet</h2>
                        <p className="mb-6 text-sm leading-relaxed text-slate-400">
                            Create a campaign group, or join one with an invite code from its owner.
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                        {groups.map((group) => (
                            <Link
                                key={group.id}
                                href={`/groups/${group.id}`}
                                className="group flex min-h-48 flex-col justify-between rounded-xl border border-slate-700/80 bg-[#1a232e] p-5 shadow-[0_10px_22px_rgba(0,0,0,0.12)] transition hover:-translate-y-0.5 hover:border-amber-200/45 hover:bg-[#1d2834]"
                            >
                                <div>
                                    <div className="flex items-start justify-between gap-3 mb-3">
                                        <div className="flex size-10 items-center justify-center rounded-lg border border-amber-200/25 bg-amber-200/10 font-serif text-lg font-bold text-amber-100">
                                            {group.name.slice(0, 2).toUpperCase()}
                                        </div>
                                        <span
                                            className={clsx(
                                                "inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full",
                                                group.role === "owner"
                                                    ? "border border-amber-200/25 bg-amber-200/10 text-amber-100"
                                                    : "bg-slate-700/70 text-slate-300"
                                            )}
                                        >
                                            {group.role === "owner" && <Crown size={12} />}
                                            {group.role === "owner" ? "Owner" : "Member"}
                                        </span>
                                    </div>

                                    <h3 className="mb-1 font-serif text-xl font-bold text-stone-100 transition group-hover:text-amber-100">
                                        {group.name}
                                    </h3>

                                    <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
                                        <span className="flex items-center gap-1">
                                            <Users size={14} />
                                            {group.member_count} {group.member_count === 1 ? "player" : "players"}
                                        </span>
                                        <span className="flex items-center gap-1">
                                            <Calendar size={14} />
                                            {group.timezone}
                                        </span>
                                    </div>
                                </div>

                                <div className="mt-6 flex items-center justify-between border-t border-slate-700/70 pt-4 text-xs font-semibold text-amber-200">
                                    <span>Open Workspace</span>
                                    <ArrowRight size={14} className="group-hover:translate-x-1 transition" />
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </main>

            {(isCreateOpen || isJoinOpen) && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
                    <button
                        aria-label="Close dialog"
                        className="absolute inset-0 bg-slate-950/50"
                        onClick={isCreateOpen ? closeCreate : closeJoin}
                    />
                    <form
                        onSubmit={isCreateOpen ? handleCreateGroup : handleJoinGroup}
                        className="relative w-full max-w-md rounded-xl border border-slate-700 bg-[#1a232e] p-6 text-slate-100 shadow-2xl"
                    >
                        <div className="mb-5 flex items-start justify-between gap-4">
                            <div>
                                <h2 className="font-serif text-xl font-bold text-stone-100">
                                    {isCreateOpen ? "Create group" : "Join with code"}
                                </h2>
                                <p className="mt-1 text-xs text-slate-400">
                                    {isCreateOpen
                                        ? "You will become this group's owner."
                                        : "Ask a group owner for their current join code."}
                                </p>
                            </div>
                            <button
                                type="button"
                                aria-label="Close dialog"
                                onClick={isCreateOpen ? closeCreate : closeJoin}
                                className="rounded-md p-1 text-slate-400 transition hover:bg-slate-700 hover:text-amber-100"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        {isCreateOpen ? (
                            <>
                                <label className="mb-3 block text-xs font-bold text-slate-200">
                                    Group name
                                    <input
                                        autoFocus
                                        value={groupName}
                                        onChange={(event) => setGroupName(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-amber-200/70"
                                    />
                                </label>
                                <label className="block text-xs font-bold text-slate-200">
                                    Description <span className="font-normal text-slate-400">(optional)</span>
                                    <textarea
                                        value={groupDescription}
                                        onChange={(event) => setGroupDescription(event.target.value)}
                                        maxLength={2000}
                                        rows={3}
                                        className="mt-1.5 w-full resize-none rounded-md border border-slate-600 bg-[#111820] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-amber-200/70"
                                    />
                                </label>
                                <label className="mt-3 block text-xs font-bold text-slate-200">
                                    Your name in this group <span className="font-normal text-slate-400">(optional)</span>
                                    <input
                                        value={groupNickname}
                                        onChange={(event) => setGroupNickname(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-amber-200/70"
                                    />
                                </label>
                            </>
                        ) : (
                            <>
                                <label className="block text-xs font-bold text-slate-200">
                                    Join code
                                    <input
                                        autoFocus
                                        value={joinCode}
                                        onChange={(event) => setJoinCode(formatInviteCodeInput(event.target.value))}
                                        placeholder="K7M4-PQ2X"
                                        maxLength={12}
                                        className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2 font-mono text-sm uppercase tracking-widest text-slate-100 outline-none transition focus:border-amber-200/70"
                                    />
                                </label>
                                <label className="mt-3 block text-xs font-bold text-slate-200">
                                    Your name in this group <span className="font-normal text-slate-400">(optional)</span>
                                    <input
                                        value={joinNickname}
                                        onChange={(event) => setJoinNickname(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-amber-200/70"
                                    />
                                </label>
                            </>
                        )}

                        {formError && <p className="mt-4 text-xs font-semibold text-rose-600 dark:text-rose-300">{formError}</p>}
                        <button
                            disabled={isSubmitting}
                            className="mt-5 inline-flex w-full items-center justify-center rounded-md bg-[#d5a75b] px-4 py-2.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {isSubmitting ? "Working..." : isCreateOpen ? "Create group" : "Join group"}
                        </button>
                    </form>
                </div>
            )}
        </div>
    );
}
