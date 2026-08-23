"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
    ArrowLeft,
    Crown,
    LoaderCircle,
    LogOut,
    Settings2,
    Shield,
    Trash2,
    Users,
} from "lucide-react";

import { AppHeader, SurfacePanel } from "@/components/AppShell";
import { canLeaveGroup, memberManagementActions } from "@/lib/groupManagement";
import {
    deleteGroup,
    fetchGroupDetail,
    fetchOnboardingStatus,
    leaveGroup,
    removeGroupMember,
    transferGroupOwnership,
    updateGroupMemberRole,
    updateGroupName,
    type GroupDetail,
    type GroupMember,
} from "@/services/api";

function roleLabel(role: GroupMember["role"]): string {
    return role === "owner" ? "Owner" : role === "organizer" ? "Organizer" : "Member";
}

export default function GroupSettingsPage({
    params,
}: {
    params: Promise<{ groupId: string }>;
}) {
    const { groupId } = use(params);
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const [group, setGroup] = useState<GroupDetail | null>(null);
    const [name, setName] = useState("");
    const [transferUserId, setTransferUserId] = useState("");
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const loadGroup = useCallback(async () => {
        if (!isLoaded) return;
        try {
            setIsLoading(true);
            const token = await getToken();
            const onboarding = await fetchOnboardingStatus(token);
            if (!onboarding.linked) {
                router.replace(`/onboarding?next=/groups/${groupId}/settings`);
                return;
            }
            const detail = await fetchGroupDetail(groupId, token);
            setGroup(detail);
            setName(detail.name);
            setTransferUserId((current) =>
                detail.members.some((member) => member.id === current) ? current : ""
            );
            setError(null);
        } catch (loadError) {
            console.error("Failed to load group settings:", loadError);
            setError("Unable to load this group’s settings. You may no longer be a member.");
        } finally {
            setIsLoading(false);
        }
    }, [getToken, groupId, isLoaded, router]);

    useEffect(() => {
        void loadGroup();
    }, [loadGroup]);

    const perform = async (action: () => Promise<void>, successMessage: string) => {
        try {
            setIsSaving(true);
            setError(null);
            setNotice(null);
            await action();
            await loadGroup();
            setNotice(successMessage);
        } catch (actionError) {
            console.error("Group settings update failed:", actionError);
            setError(actionError instanceof Error ? actionError.message : "Could not update group settings.");
        } finally {
            setIsSaving(false);
        }
    };

    const handleRename = () => {
        if (!group || !name.trim()) return;
        void perform(async () => {
            const token = await getToken();
            await updateGroupName(groupId, name, token);
        }, "Group name updated.");
    };

    const handleRoleChange = (member: GroupMember, role: "organizer" | "member") => {
        void perform(async () => {
            const token = await getToken();
            await updateGroupMemberRole(groupId, member.id, role, token);
        }, `${member.display_name} is now an ${role}.`);
    };

    const handleRemove = (member: GroupMember) => {
        if (!window.confirm(`Remove ${member.display_name} from ${group?.name}?`)) return;
        void perform(async () => {
            const token = await getToken();
            await removeGroupMember(groupId, member.id, token);
        }, `${member.display_name} was removed from the group.`);
    };

    const handleLeave = () => {
        if (!window.confirm(`Leave ${group?.name}? You will need a new invite to rejoin.`)) return;
        void (async () => {
            try {
                setIsSaving(true);
                const token = await getToken();
                await leaveGroup(groupId, token);
                router.replace("/app");
            } catch (leaveError) {
                setError(leaveError instanceof Error ? leaveError.message : "Could not leave the group.");
                setIsSaving(false);
            }
        })();
    };

    const handleTransfer = () => {
        if (!group || !transferUserId) return;
        const nextOwner = group.members.find((member) => member.id === transferUserId);
        if (!nextOwner || !window.confirm(`Transfer ownership of ${group.name} to ${nextOwner.display_name}? You will become a member.`)) {
            return;
        }
        void perform(async () => {
            const token = await getToken();
            await transferGroupOwnership(groupId, nextOwner.id, token);
        }, `Ownership transferred to ${nextOwner.display_name}. Your permissions have been refreshed.`);
    };

    const handleDelete = () => {
        if (!group || !window.confirm(`Delete ${group.name}? This removes its invites and confirmed sessions. This cannot be undone.`)) {
            return;
        }
        void (async () => {
            try {
                setIsSaving(true);
                const token = await getToken();
                await deleteGroup(groupId, token);
                router.replace("/app");
            } catch (deleteError) {
                setError(deleteError instanceof Error ? deleteError.message : "Could not delete the group.");
                setIsSaving(false);
            }
        })();
    };

    const currentMember = group?.members.find((member) => member.id === group.current_user_id);
    const ownershipCandidates = group?.members.filter((member) => member.id !== group.current_user_id) ?? [];

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <AppHeader
                context={
                    <Link href={`/groups/${groupId}`} className="hidden items-center gap-2 text-xs font-semibold text-slate-300 transition hover:text-amber-100 sm:flex">
                        <ArrowLeft size={15} />
                        {group?.name || "Group"}
                    </Link>
                }
            />
            <main className="mx-auto w-full max-w-5xl px-4 py-7 sm:px-6">
                {isLoading ? (
                    <div className="space-y-5 animate-pulse">
                        <div className="h-28 rounded-xl border border-slate-700/80 bg-[#1a232e]" />
                        <div className="h-72 rounded-xl border border-slate-700/80 bg-[#1a232e]" />
                    </div>
                ) : error && !group ? (
                    <SurfacePanel className="mx-auto max-w-lg p-8 text-center">
                        <Shield className="mx-auto mb-3 text-rose-300" size={34} />
                        <h1 className="font-serif text-2xl font-bold text-stone-100">Settings unavailable</h1>
                        <p className="mt-2 text-sm text-slate-400">{error}</p>
                        <Link href="/app" className="mt-6 inline-flex rounded-md bg-[#d5a75b] px-4 py-2 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77]">
                            Return to dashboard
                        </Link>
                    </SurfacePanel>
                ) : group && currentMember ? (
                    <div className="space-y-5">
                        <div className="flex flex-col gap-3 border-b border-slate-700/80 pb-5 sm:flex-row sm:items-end sm:justify-between">
                            <div>
                                <div className="flex items-center gap-2 text-amber-200/70">
                                    <Settings2 size={17} />
                                    <span className="text-[10px] font-bold uppercase tracking-[0.2em]">Group settings</span>
                                </div>
                                <h1 className="mt-2 font-serif text-3xl font-bold text-stone-100">{group.name}</h1>
                                <p className="mt-1 text-sm text-slate-400">Manage this campaign and its adventurers.</p>
                            </div>
                            <Link href={`/groups/${groupId}`} className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:border-amber-200/50 hover:text-amber-100">
                                <ArrowLeft size={14} /> Back to calendar
                            </Link>
                        </div>

                        {error && <p className="rounded-lg border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs font-semibold text-rose-100">{error}</p>}
                        {notice && <p className="rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-xs font-semibold text-emerald-100">{notice}</p>}

                        <SurfacePanel className="p-5 sm:p-6">
                            <div className="flex items-center gap-2">
                                <Settings2 size={17} className="text-amber-200" />
                                <h2 className="font-serif text-xl font-bold text-stone-100">General</h2>
                            </div>
                            <p className="mt-1 text-xs text-slate-400">The group name appears in calendars, schedules, and invites.</p>
                            {group.role === "owner" ? (
                                <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
                                    <label className="flex-1 text-xs font-semibold text-slate-300">
                                        Group name
                                        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} disabled={isSaving} className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#141c26] px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-amber-200/70 disabled:opacity-60" />
                                    </label>
                                    <button onClick={handleRename} disabled={isSaving || !name.trim() || name.trim() === group.name} className="rounded-md bg-[#d5a75b] px-4 py-2.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-50">Save name</button>
                                </div>
                            ) : (
                                <p className="mt-4 rounded-md border border-slate-700 bg-[#141c26]/70 px-3 py-2.5 text-xs text-slate-400">Only the owner can rename this group.</p>
                            )}
                        </SurfacePanel>

                        <SurfacePanel className="p-5 sm:p-6">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Users size={18} className="text-amber-200" />
                                    <h2 className="font-serif text-xl font-bold text-stone-100">Members</h2>
                                </div>
                                <span className="rounded-full border border-slate-600 bg-slate-800/80 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-300">{group.members.length} adventurers</span>
                            </div>
                            <div className="mt-4 divide-y divide-slate-700/70 overflow-hidden rounded-lg border border-slate-700/80 bg-[#141c26]/65">
                                {group.members.map((member) => {
                                    const actions = memberManagementActions(group.role, member.role, member.id === group.current_user_id);
                                    const isCurrentUser = member.id === group.current_user_id;
                                    return (
                                        <div key={member.id} className="flex flex-col gap-3 p-3.5 sm:flex-row sm:items-center sm:justify-between">
                                            <div className="flex min-w-0 items-center gap-3">
                                                <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-slate-600 bg-slate-800 text-xs font-bold text-slate-100">{member.display_name.slice(0, 2).toUpperCase()}</span>
                                                <div className="min-w-0">
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <span className="truncate text-sm font-semibold text-slate-100">{member.display_name}</span>
                                                        {isCurrentUser && <span className="text-[10px] font-bold text-amber-200">YOU</span>}
                                                        {member.role === "owner" && <Crown size={13} className="text-amber-200" />}
                                                    </div>
                                                    <p className="mt-0.5 text-[11px] text-slate-500">{member.nickname ? "Using a group nickname" : "Using their display name"}</p>
                                                </div>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                                                <span className="rounded-full border border-slate-600 bg-slate-800 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-300">{roleLabel(member.role)}</span>
                                                {actions.canPromote && <button onClick={() => handleRoleChange(member, "organizer")} disabled={isSaving} className="rounded-md border border-amber-200/35 px-2.5 py-1.5 text-[11px] font-bold text-amber-100 transition hover:bg-amber-200/10 disabled:opacity-50">Promote</button>}
                                                {actions.canDemote && <button onClick={() => handleRoleChange(member, "member")} disabled={isSaving} className="rounded-md border border-slate-600 px-2.5 py-1.5 text-[11px] font-bold text-slate-300 transition hover:bg-slate-800 disabled:opacity-50">Demote</button>}
                                                {actions.canRemove && <button onClick={() => handleRemove(member)} disabled={isSaving} className="rounded-md border border-rose-400/30 px-2.5 py-1.5 text-[11px] font-bold text-rose-200 transition hover:bg-rose-400/10 disabled:opacity-50">Remove</button>}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </SurfacePanel>

                        <SurfacePanel className="p-5 sm:p-6">
                            <div className="flex items-center gap-2">
                                <Crown size={18} className="text-amber-200" />
                                <h2 className="font-serif text-xl font-bold text-stone-100">Ownership</h2>
                            </div>
                            {group.role === "owner" ? (
                                <div className="mt-3 rounded-lg border border-amber-200/20 bg-amber-200/[0.05] p-4">
                                    <p className="text-xs text-slate-300">Transfer ownership before you leave. The new owner receives full group controls; you become a member.</p>
                                    {ownershipCandidates.length ? (
                                        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                                            <select value={transferUserId} onChange={(event) => setTransferUserId(event.target.value)} disabled={isSaving} className="min-w-0 flex-1 rounded-md border border-slate-600 bg-[#141c26] px-3 py-2 text-sm text-slate-100 outline-none focus:border-amber-200/70">
                                                <option value="">Select a new owner</option>
                                                {ownershipCandidates.map((member) => <option key={member.id} value={member.id}>{member.display_name} — {roleLabel(member.role)}</option>)}
                                            </select>
                                            <button onClick={handleTransfer} disabled={isSaving || !transferUserId} className="inline-flex items-center justify-center gap-2 rounded-md border border-amber-200/45 px-4 py-2 text-xs font-bold text-amber-100 transition hover:bg-amber-200/10 disabled:cursor-not-allowed disabled:opacity-50"><Crown size={14} /> Transfer ownership</button>
                                        </div>
                                    ) : <p className="mt-3 text-xs text-slate-400">Invite another member before transferring ownership.</p>}
                                </div>
                            ) : (
                                <p className="mt-3 rounded-md border border-slate-700 bg-[#141c26]/70 px-3 py-2.5 text-xs text-slate-400">Only the current owner can transfer ownership.</p>
                            )}
                        </SurfacePanel>

                        <SurfacePanel className="border-rose-400/25 p-5 sm:p-6">
                            <div className="flex items-center gap-2">
                                <Trash2 size={18} className="text-rose-200" />
                                <h2 className="font-serif text-xl font-bold text-stone-100">Danger Zone</h2>
                            </div>
                            <div className="mt-4 grid gap-4 lg:grid-cols-2">
                                <div className="rounded-lg border border-slate-700 bg-[#141c26]/70 p-4">
                                    <div className="flex items-start justify-between gap-4">
                                        <div><h3 className="text-sm font-bold text-slate-100">Leave group</h3><p className="mt-1 text-xs text-slate-400">Your account and availability remain intact.</p></div>
                                        {canLeaveGroup(group.role) ? <button onClick={handleLeave} disabled={isSaving} className="shrink-0 rounded-md border border-rose-400/30 px-3 py-2 text-xs font-bold text-rose-200 transition hover:bg-rose-400/10 disabled:opacity-50"><LogOut size={13} className="mr-1 inline" /> Leave</button> : <span className="text-right text-[11px] text-slate-500">Transfer ownership first</span>}
                                    </div>
                                </div>
                                <div className="rounded-lg border border-rose-400/20 bg-rose-400/[0.04] p-4">
                                    <div className="flex items-start justify-between gap-4">
                                        <div><h3 className="text-sm font-bold text-rose-100">Delete group</h3><p className="mt-1 text-xs text-slate-400">Deletes this group, its invite, and its confirmed sessions only.</p></div>
                                        {group.role === "owner" ? <button onClick={handleDelete} disabled={isSaving} className="shrink-0 rounded-md bg-rose-400/15 px-3 py-2 text-xs font-bold text-rose-100 transition hover:bg-rose-400/25 disabled:opacity-50"><Trash2 size={13} className="mr-1 inline" /> Delete</button> : <span className="text-right text-[11px] text-slate-500">Owner only</span>}
                                    </div>
                                </div>
                            </div>
                        </SurfacePanel>
                    </div>
                ) : null}
                {isSaving && <div className="fixed bottom-5 right-5 inline-flex items-center gap-2 rounded-full border border-amber-200/30 bg-[#1a232e] px-3 py-2 text-xs font-semibold text-amber-100 shadow-xl"><LoaderCircle size={14} className="animate-spin" /> Updating group</div>}
            </main>
        </div>
    );
}
