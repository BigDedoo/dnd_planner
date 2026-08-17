"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import { createGroup, fetchMyGroups, fetchOnboardingStatus, joinGroupWithCode, MyGroup } from "@/services/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import { formatInviteCodeInput } from "@/lib/inviteCode";
import { ArrowRight, Calendar, Crown, KeyRound, Plus, Shield, Users, X } from "lucide-react";
import clsx from "clsx";

export default function AppDashboard() {
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const [groups, setGroups] = useState<MyGroup[]>([]);
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
                const userGroups = await fetchMyGroups(token);
                if (active) {
                    setGroups(userGroups);
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
        <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col">
            {/* Top Navigation Shell */}
            <header className="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
                <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Link href="/app" className="flex items-center gap-3 group">
                            <div className="size-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 text-xl font-bold group-hover:scale-105 transition">
                                🎲
                            </div>
                            <div>
                                <span className="font-extrabold text-lg tracking-tight">DnD Planner</span>
                                <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300">
                                    Dashboard
                                </span>
                            </div>
                        </Link>
                    </div>

                    <div className="flex items-center gap-3">
                        <ThemeToggle />
                        <div className="h-6 w-px bg-slate-200 dark:bg-slate-800" />
                        <UserButton />
                    </div>
                </div>
            </header>

            {/* Dashboard Content */}
            <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-10">
                <div className="mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <h1 className="text-3xl font-extrabold tracking-tight">My Groups</h1>
                        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                            Campaign workspaces where your profile has active membership.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <button
                            onClick={() => { setFormError(null); setIsCreateOpen(true); }}
                            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700"
                        >
                            <Plus size={15} /> Create group
                        </button>
                        <button
                            onClick={() => { setFormError(null); setIsJoinOpen(true); }}
                            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
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

                {isLoading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {[1, 2, 3].map((i) => (
                            <div
                                key={i}
                                className="h-44 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 animate-pulse"
                            >
                                <div className="h-5 bg-slate-200 dark:bg-slate-800 rounded w-1/2 mb-4" />
                                <div className="h-4 bg-slate-100 dark:bg-slate-800/60 rounded w-1/3 mb-8" />
                                <div className="h-4 bg-slate-100 dark:bg-slate-800/60 rounded w-2/3" />
                            </div>
                        ))}
                    </div>
                ) : groups.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 p-12 text-center max-w-xl mx-auto my-12">
                        <div className="size-16 rounded-2xl bg-blue-50 dark:bg-blue-950/60 border border-blue-100 dark:border-blue-900/50 flex items-center justify-center text-blue-600 dark:text-blue-400 mx-auto mb-4">
                            <Shield size={32} />
                        </div>
                        <h2 className="text-xl font-bold mb-2">You don&apos;t belong to any groups yet</h2>
                        <p className="text-sm text-slate-500 dark:text-slate-400 mb-6 leading-relaxed">
                            Create a campaign group, or join one with an invite code from its owner.
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {groups.map((group) => (
                            <Link
                                key={group.id}
                                href={`/groups/${group.id}`}
                                className="group rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm hover:shadow-md hover:border-blue-500/50 dark:hover:border-blue-500/50 transition flex flex-col justify-between"
                            >
                                <div>
                                    <div className="flex items-start justify-between gap-3 mb-3">
                                        <div className="size-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-sm">
                                            {group.name.slice(0, 2).toUpperCase()}
                                        </div>
                                        <span
                                            className={clsx(
                                                "inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full",
                                                group.role === "owner"
                                                    ? "bg-amber-100 dark:bg-amber-950/70 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-900/50"
                                                    : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                                            )}
                                        >
                                            {group.role === "owner" && <Crown size={12} />}
                                            {group.role === "owner" ? "Owner" : "Member"}
                                        </span>
                                    </div>

                                    <h3 className="text-xl font-bold group-hover:text-blue-600 dark:group-hover:text-blue-400 transition mb-1">
                                        {group.name}
                                    </h3>

                                    <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400 mt-3">
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

                                <div className="pt-6 mt-6 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-xs font-semibold text-blue-600 dark:text-blue-400">
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
                        className="relative w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900"
                    >
                        <div className="mb-5 flex items-start justify-between gap-4">
                            <div>
                                <h2 className="text-lg font-extrabold">
                                    {isCreateOpen ? "Create group" : "Join with code"}
                                </h2>
                                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                    {isCreateOpen
                                        ? "You will become this group's owner."
                                        : "Ask a group owner for their current join code."}
                                </p>
                            </div>
                            <button
                                type="button"
                                aria-label="Close dialog"
                                onClick={isCreateOpen ? closeCreate : closeJoin}
                                className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        {isCreateOpen ? (
                            <>
                                <label className="mb-3 block text-xs font-bold text-slate-700 dark:text-slate-200">
                                    Group name
                                    <input
                                        autoFocus
                                        value={groupName}
                                        onChange={(event) => setGroupName(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                </label>
                                <label className="block text-xs font-bold text-slate-700 dark:text-slate-200">
                                    Description <span className="font-normal text-slate-400">(optional)</span>
                                    <textarea
                                        value={groupDescription}
                                        onChange={(event) => setGroupDescription(event.target.value)}
                                        maxLength={2000}
                                        rows={3}
                                        className="mt-1.5 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                </label>
                                <label className="mt-3 block text-xs font-bold text-slate-700 dark:text-slate-200">
                                    Your name in this group <span className="font-normal text-slate-400">(optional)</span>
                                    <input
                                        value={groupNickname}
                                        onChange={(event) => setGroupNickname(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                </label>
                            </>
                        ) : (
                            <>
                                <label className="block text-xs font-bold text-slate-700 dark:text-slate-200">
                                    Join code
                                    <input
                                        autoFocus
                                        value={joinCode}
                                        onChange={(event) => setJoinCode(formatInviteCodeInput(event.target.value))}
                                        placeholder="K7M4-PQ2X"
                                        maxLength={12}
                                        className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm uppercase tracking-widest outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                </label>
                                <label className="mt-3 block text-xs font-bold text-slate-700 dark:text-slate-200">
                                    Your name in this group <span className="font-normal text-slate-400">(optional)</span>
                                    <input
                                        value={joinNickname}
                                        onChange={(event) => setJoinNickname(event.target.value)}
                                        maxLength={120}
                                        className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950"
                                    />
                                </label>
                            </>
                        )}

                        {formError && <p className="mt-4 text-xs font-semibold text-rose-600 dark:text-rose-300">{formError}</p>}
                        <button
                            disabled={isSubmitting}
                            className="mt-5 inline-flex w-full items-center justify-center rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {isSubmitting ? "Working..." : isCreateOpen ? "Create group" : "Join group"}
                        </button>
                    </form>
                </div>
            )}
        </div>
    );
}
