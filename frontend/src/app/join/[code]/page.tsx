"use client";

import { FormEvent, use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { ArrowRight, CheckCircle2, KeyRound, UsersRound } from "lucide-react";

import { AppBrand } from "@/components/AppShell";
import { ThemeToggle } from "@/components/ThemeToggle";
import { directInvitePath } from "@/lib/directInvite";
import { formatInviteCodeInput } from "@/lib/inviteCode";
import { fetchOnboardingStatus, joinGroupWithCode, previewGroupInvite } from "@/services/api";

export default function DirectInvitePage({ params }: { params: Promise<{ code: string }> }) {
    const { code } = use(params);
    return <DirectInviteContent code={code} />;
}

function DirectInviteContent({ code }: { code: string }) {
    const { getToken, isLoaded, isSignedIn } = useAuth();
    const router = useRouter();
    const inviteCode = useMemo(() => formatInviteCodeInput(code), [code]);
    const invitePath = useMemo(() => directInvitePath(inviteCode), [inviteCode]);
    const [groupName, setGroupName] = useState<string | null>(null);
    const [nickname, setNickname] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isChecking, setIsChecking] = useState(false);
    const [isJoining, setIsJoining] = useState(false);

    useEffect(() => {
        if (!isLoaded || !isSignedIn) return;
        let active = true;
        const prepareInvite = async () => {
            try {
                setIsChecking(true);
                setError(null);
                const token = await getToken();
                const onboarding = await fetchOnboardingStatus(token);
                if (!active) return;
                if (!onboarding.linked) {
                    router.replace(`/onboarding?next=${encodeURIComponent(invitePath)}`);
                    return;
                }
                const invite = await previewGroupInvite(inviteCode, token);
                if (active) setGroupName(invite.group_name);
            } catch (err) {
                if (active) setError(err instanceof Error ? err.message : "This invite is unavailable.");
            } finally {
                if (active) setIsChecking(false);
            }
        };
        void prepareInvite();
        return () => { active = false; };
    }, [getToken, inviteCode, invitePath, isLoaded, isSignedIn, router]);

    const handleJoin = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        try {
            setIsJoining(true);
            setError(null);
            const token = await getToken();
            const group = await joinGroupWithCode(inviteCode, nickname || undefined, token);
            router.replace(`/groups/${group.id}`);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not join this group.");
        } finally {
            setIsJoining(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <header className="border-b border-slate-700/70 bg-[#141c26]/95 backdrop-blur-xl">
                <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4 sm:px-6">
                    <AppBrand />
                    <div className="flex items-center gap-2"><ThemeToggle /><Show when="signed-in"><UserButton /></Show></div>
                </div>
            </header>
            <main className="mx-auto flex min-h-[calc(100vh-56px)] max-w-lg items-center px-4 py-10 sm:px-6">
                <section className="w-full overflow-hidden rounded-2xl border border-slate-700/80 bg-[#1a232e] shadow-[0_24px_60px_rgba(0,0,0,0.28)]">
                    <div className="border-b border-amber-200/15 bg-[radial-gradient(circle_at_top_right,rgba(213,167,91,0.18),transparent_45%)] px-6 py-7 sm:px-8">
                        <div className="flex size-11 items-center justify-center rounded-lg border border-amber-200/25 bg-amber-200/10 text-amber-200"><KeyRound size={20} /></div>
                        <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/70">Group invitation</p>
                        <h1 className="mt-1 font-serif text-3xl font-bold text-stone-100">Join a campaign</h1>
                        <p className="mt-2 text-sm leading-6 text-slate-400">You&apos;ve been invited to plan the next session with a group.</p>
                    </div>

                    <div className="p-6 sm:p-8">
                        {!isLoaded ? (
                            <LoadingInvite />
                        ) : !isSignedIn ? (
                            <div>
                                <p className="text-sm leading-6 text-slate-300">Sign in or create an account to view this invitation and join the group.</p>
                                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                                    <SignUpButton mode="modal" forceRedirectUrl={invitePath}>
                                        <button className="inline-flex items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-4 py-2.5 text-sm font-bold text-[#18140f] transition hover:bg-[#e4bc77]">Create account <ArrowRight size={16} /></button>
                                    </SignUpButton>
                                    <SignInButton mode="modal" forceRedirectUrl={invitePath}>
                                        <button className="rounded-md border border-slate-600 bg-slate-800/70 px-4 py-2.5 text-sm font-bold text-slate-100 transition hover:border-slate-500 hover:bg-slate-700">Sign in</button>
                                    </SignInButton>
                                </div>
                            </div>
                        ) : isChecking ? (
                            <LoadingInvite />
                        ) : error ? (
                            <InviteError message={error} />
                        ) : groupName ? (
                            <form onSubmit={handleJoin}>
                                <div className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.05] p-4">
                                    <div className="flex items-center gap-2 text-emerald-200"><CheckCircle2 size={17} /><span className="text-xs font-bold uppercase tracking-[0.14em]">Invite verified</span></div>
                                    <p className="mt-2 font-serif text-2xl font-bold text-stone-100">{groupName}</p>
                                </div>
                                <label className="mt-6 block text-xs font-bold text-slate-200">
                                    Your name in this group <span className="font-normal text-slate-500">(optional)</span>
                                    <input value={nickname} onChange={(event) => setNickname(event.target.value)} maxLength={120} placeholder="Use your global display name" className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-amber-200/70" />
                                </label>
                                <p className="mt-2 text-xs leading-5 text-slate-500">This nickname is only shown inside this group. You can change it later.</p>
                                <button disabled={isJoining} className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-4 py-2.5 text-sm font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60">
                                    <UsersRound size={16} /> {isJoining ? "Joining group..." : "Join group"}
                                </button>
                            </form>
                        ) : null}
                    </div>
                </section>
            </main>
        </div>
    );
}

function LoadingInvite() {
    return <div className="space-y-4"><div className="h-5 w-28 animate-pulse rounded bg-slate-700/80" /><div className="h-10 animate-pulse rounded bg-slate-800/80" /><p className="text-sm text-slate-400">Checking your invitation…</p></div>;
}

function InviteError({ message }: { message: string }) {
    return <div><div className="rounded-xl border border-rose-300/20 bg-rose-300/[0.05] p-4"><p className="font-semibold text-rose-200">This invitation isn&apos;t available</p><p className="mt-1 text-sm leading-6 text-slate-400">{message === "Invite code is invalid or has been revoked" ? "It may have been revoked or replaced by the group owner." : "Please try again, or ask the group owner for a new invite link."}</p></div><Link href="/app" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-amber-200 transition hover:text-amber-100">Go to dashboard <ArrowRight size={15} /></Link></div>;
}
