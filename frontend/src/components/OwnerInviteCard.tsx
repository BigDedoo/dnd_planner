"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { KeyRound } from "lucide-react";

import { directInviteUrl } from "@/lib/directInvite";
import {
    confirmedInviteMutation,
    copyInviteText,
    inviteCreatedLabel,
    inviteUseCountLabel,
    shareInviteLink,
} from "@/lib/invitePresentation";
import {
    fetchGroupInviteStatus,
    generateGroupInvite,
    revokeGroupInvite,
    type GroupInviteStatus,
} from "@/services/api";

interface OwnerInviteCardViewProps {
    status: GroupInviteStatus | null;
    code: string | null;
    url: string | null;
    loading: boolean;
    updating: boolean;
    canShare: boolean;
    error: string | null;
    notice: string | null;
    onGenerate: () => void;
    onRevoke: () => void;
    onCopyLink: () => void;
    onCopyCode: () => void;
    onShare: () => void;
    onRetry: () => void;
}

export function OwnerInviteCardView({
    status, code, url, loading, updating, canShare, error, notice,
    onGenerate, onRevoke, onCopyLink, onCopyCode, onShare, onRetry,
}: OwnerInviteCardViewProps) {
    const active = status?.active === true;
    return <section aria-label="Invite players" className="min-w-0 rounded-xl border border-slate-700/80 bg-[#1a232e] p-4 shadow-[0_10px_24px_rgba(0,0,0,0.12)] sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
                <div className="flex items-center gap-2">
                    <KeyRound size={16} className="shrink-0 text-slate-300" />
                    <h2 className="text-sm font-bold text-stone-100">Invite players</h2>
                </div>
                {!active && !loading && <p className="mt-1 text-xs text-slate-400">Create a reusable invite link for this group.</p>}
            </div>
            {active && <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300">Active</span>}
        </div>

        {loading ? <p className="mt-4 text-xs text-slate-400">Checking invite status…</p> : status ? <>
            {active ? <>
                <p className="mt-3 text-xs text-slate-300">{inviteUseCountLabel(status.use_count ?? 0)}</p>
                {status.created_at && <p className="mt-1 text-[11px] text-slate-500">{inviteCreatedLabel(status.created_at)}</p>}
                {code ? <div className="mt-4 space-y-3">
                    <label className="block text-[11px] font-semibold text-slate-400">Join code
                        <input aria-label="Invite code" readOnly value={code} onFocus={(event) => event.currentTarget.select()} className="mt-1 block w-full min-w-0 rounded-md border border-slate-700 bg-[#111820] px-3 py-2 font-mono text-sm font-bold tracking-widest text-stone-100" />
                    </label>
                    {url && <label className="block text-[11px] font-semibold text-slate-400">Invite link · select to copy manually
                        <input aria-label="Invite link to copy manually" readOnly value={url} onFocus={(event) => event.currentTarget.select()} className="mt-1 block w-full min-w-0 rounded-md border border-slate-700 bg-[#111820] px-3 py-2 text-xs text-slate-200" />
                    </label>}
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                        <button type="button" onClick={onCopyLink} disabled={!url} className="min-h-10 rounded-md bg-amber-200 px-3 py-2 text-xs font-bold text-[#201a12] transition hover:bg-amber-100 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-amber-100">Copy link</button>
                        <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={onCopyCode} className="min-h-10 rounded-md border border-slate-600 px-3 py-2 text-xs font-bold text-slate-200 transition hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-amber-200">Copy code</button>
                            {canShare && url && <button type="button" onClick={onShare} className="min-h-10 rounded-md border border-slate-600 px-3 py-2 text-xs font-bold text-slate-200 transition hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-amber-200">Share</button>}
                        </div>
                    </div>
                </div> : <p className="mt-3 text-xs leading-5 text-slate-400">This invite is still valid, but its code is not stored in a recoverable form. If you no longer have the link, replace it with a new one.</p>}
                <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-700/70 pt-3">
                    <button type="button" onClick={onGenerate} disabled={updating} className="min-h-10 rounded-md border border-amber-200/30 bg-amber-200/10 px-3 py-2 text-xs font-bold text-amber-100 transition hover:bg-amber-200/20 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-amber-200">Replace invite</button>
                    <button type="button" onClick={onRevoke} disabled={updating} className="min-h-10 rounded-md px-3 py-2 text-xs font-bold text-rose-200 transition hover:bg-rose-950/40 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-rose-300">Revoke invite</button>
                </div>
            </> : <button type="button" onClick={onGenerate} disabled={updating} className="mt-4 min-h-10 rounded-md bg-amber-200 px-3 py-2 text-xs font-bold text-[#201a12] transition hover:bg-amber-100 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-amber-100">Create invite link</button>}
        </> : <button type="button" onClick={onRetry} className="mt-4 min-h-10 rounded-md border border-slate-600 px-3 py-2 text-xs font-bold text-slate-200">Retry status</button>}
        {notice && <p role="status" aria-live="polite" className="mt-3 text-xs font-semibold text-emerald-200">{notice}</p>}
        {error && <p role="alert" className="mt-3 text-xs font-semibold text-rose-200">{error}</p>}
    </section>;
}

export function OwnerInviteCard({ groupId, groupName }: { groupId: string; groupName: string }) {
    const { getToken } = useAuth();
    const [status, setStatus] = useState<GroupInviteStatus | null>(null);
    const [code, setCode] = useState<string | null>(null);
    const [origin, setOrigin] = useState<string | null>(null);
    const [canShare, setCanShare] = useState(false);
    const [loading, setLoading] = useState(true);
    const [updating, setUpdating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [retryKey, setRetryKey] = useState(0);
    const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const updatingRef = useRef(false);
    const url = code && origin ? directInviteUrl(origin, code) : null;

    useEffect(() => {
        setOrigin(window.location.origin);
        setCanShare(typeof navigator.share === "function");
        return () => { if (noticeTimer.current) clearTimeout(noticeTimer.current); };
    }, []);

    useEffect(() => {
        let active = true;
        const load = async () => {
            setLoading(true);
            setError(null);
            try {
                const token = await getToken();
                const next = await fetchGroupInviteStatus(groupId, token);
                if (active) setStatus(next);
            } catch (err) {
                if (active) setError(err instanceof Error ? err.message : "Could not load invite status.");
            } finally {
                if (active) setLoading(false);
            }
        };
        void load();
        return () => { active = false; };
    }, [getToken, groupId, retryKey]);

    const showNotice = (message: string) => {
        if (noticeTimer.current) clearTimeout(noticeTimer.current);
        setNotice(message);
        noticeTimer.current = setTimeout(() => setNotice(null), 3000);
    };

    const handleGenerate = async () => {
        if (!status || updatingRef.current) return;
        updatingRef.current = true;
        setUpdating(true);
        setError(null);
        setNotice(null);
        try {
            const generate = async () => generateGroupInvite(groupId, await getToken());
            const invite = status.active
                ? await confirmedInviteMutation("replace", (message) => window.confirm(message), generate)
                : await generate();
            if (!invite) return;
            setCode(invite.code);
            setStatus({ active: true, created_at: invite.created_at, use_count: invite.use_count });
            showNotice(status.active ? "Invite replaced. The previous link no longer works." : "Invite link created.");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not create the invite link.");
        } finally {
            updatingRef.current = false;
            setUpdating(false);
        }
    };

    const handleRevoke = async () => {
        if (!status?.active || updatingRef.current) return;
        updatingRef.current = true;
        setUpdating(true);
        setError(null);
        setNotice(null);
        try {
            const revoked = await confirmedInviteMutation("revoke", (message) => window.confirm(message), async () => {
                await revokeGroupInvite(groupId, await getToken());
                return true;
            });
            if (!revoked) return;
            setCode(null);
            setStatus({ active: false, created_at: null, use_count: null });
            showNotice("Invite revoked. The link no longer works.");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not revoke the invite.");
        } finally {
            updatingRef.current = false;
            setUpdating(false);
        }
    };

    const handleCopy = async (value: string | null, kind: "link" | "code") => {
        if (!value) return;
        setError(null);
        try {
            await copyInviteText(value, navigator.clipboard);
            showNotice(kind === "link" ? "Link copied" : "Code copied");
        } catch {
            setNotice(null);
            setError(kind === "link"
                ? "Copy failed. Select the invite link above and copy it manually."
                : "Copy failed. Select the code above and copy it manually.");
        }
    };

    const handleShare = async () => {
        if (!url || typeof navigator.share !== "function") return;
        setError(null);
        try {
            const result = await shareInviteLink(url, groupName, navigator.share.bind(navigator));
            if (result === "shared") showNotice("Invite shared");
        } catch {
            setError("Could not share this invite. Use Copy link or select the link above.");
        }
    };

    return <OwnerInviteCardView
        status={status} code={code} url={url} loading={loading} updating={updating}
        canShare={canShare} error={error} notice={notice}
        onGenerate={() => void handleGenerate()} onRevoke={() => void handleRevoke()}
        onCopyLink={() => void handleCopy(url, "link")}
        onCopyCode={() => void handleCopy(code, "code")}
        onShare={() => void handleShare()}
        onRetry={() => setRetryKey((value) => value + 1)}
    />;
}
