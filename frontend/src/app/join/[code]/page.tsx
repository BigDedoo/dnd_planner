"use client";

import { FormEvent, use, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { ArrowRight, KeyRound } from "lucide-react";

import { AppBrand } from "@/components/AppShell";
import { InviteJoinForm, InviteUnavailable } from "@/components/DirectInvitePanels";
import { ThemeToggle } from "@/components/ThemeToggle";
import { directInvitePath, joinAndOpenInvitedGroup } from "@/lib/directInvite";
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
    const [previewError, setPreviewError] = useState<string | null>(null);
    const [joinError, setJoinError] = useState<string | null>(null);
    const [isChecking, setIsChecking] = useState(false);
    const [isJoining, setIsJoining] = useState(false);
    const joiningRef = useRef(false);
    const redirectedRef = useRef(false);

    useEffect(() => {
        if (!isLoaded || !isSignedIn) return;
        let active = true;
        const prepareInvite = async () => {
            try {
                setIsChecking(true);
                setPreviewError(null);
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
                if (active) {
                    setGroupName(null);
                    setPreviewError(err instanceof Error ? err.message : "This invite is unavailable.");
                }
            } finally {
                if (active) setIsChecking(false);
            }
        };
        void prepareInvite();
        return () => { active = false; };
    }, [getToken, inviteCode, invitePath, isLoaded, isSignedIn, router]);

    const handleJoin = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (joiningRef.current || redirectedRef.current) return;
        joiningRef.current = true;
        try {
            setIsJoining(true);
            setJoinError(null);
            await joinAndOpenInvitedGroup(inviteCode, nickname || undefined, getToken, joinGroupWithCode, (path) => router.replace(path));
            redirectedRef.current = true;
        } catch (err) {
            const message = err instanceof Error ? err.message : "Could not join this group.";
            if (message === "Invite code is invalid or has been revoked") setPreviewError(message);
            else setJoinError(message);
        } finally {
            joiningRef.current = false;
            if (!redirectedRef.current) setIsJoining(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <header className="border-b border-slate-700/70 bg-[#141c26]/95 backdrop-blur-xl">
                <div className="mx-auto flex h-14 max-w-4xl items-center justify-between gap-2 px-4 sm:px-6">
                    <div className="min-w-0"><AppBrand compact /></div>
                    <div className="flex shrink-0 items-center gap-2"><ThemeToggle /><Show when="signed-in"><UserButton /></Show></div>
                </div>
            </header>
            <main className="mx-auto flex min-h-[calc(100vh-56px)] max-w-lg min-w-0 items-center px-4 py-10 sm:px-6">
                <section className="w-full min-w-0 overflow-hidden rounded-2xl border border-slate-700/80 bg-[#1a232e] shadow-[0_24px_60px_rgba(0,0,0,0.28)]">
                    <div className="border-b border-amber-200/15 bg-[radial-gradient(circle_at_top_right,rgba(213,167,91,0.18),transparent_45%)] px-5 py-6 sm:px-8 sm:py-7">
                        <div className="flex size-11 items-center justify-center rounded-lg border border-amber-200/25 bg-amber-200/10 text-amber-200"><KeyRound size={20} /></div>
                        <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/70">Group invitation</p>
                        <h1 className="mt-1 font-serif text-3xl font-bold text-stone-100">Join a campaign</h1>
                        <p className="mt-2 text-sm leading-6 text-slate-400">You&apos;ve been invited to plan the next session with a group.</p>
                    </div>

                    <div className="min-w-0 p-5 sm:p-8">
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
                        ) : previewError ? (
                            <InviteUnavailable message={previewError} />
                        ) : groupName ? (
                            <InviteJoinForm groupName={groupName} nickname={nickname} joining={isJoining} error={joinError} onNicknameChange={setNickname} onSubmit={handleJoin} />
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
