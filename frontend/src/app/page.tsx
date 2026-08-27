"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { ArrowRight, Dices } from "lucide-react";

import { InteractiveGroupDemo } from "@/components/InteractiveGroupDemo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { fetchOnboardingStatus } from "@/services/api";

export default function LandingPage() {
    const { getToken, isSignedIn, isLoaded } = useAuth();
    const router = useRouter();

    useEffect(() => {
        if (!isLoaded || !isSignedIn) return;
        let active = true;
        const redirectSignedInUser = async () => {
            try {
                const token = await getToken();
                const status = await fetchOnboardingStatus(token);
                if (active) router.replace(status.linked ? "/app" : "/onboarding");
            } catch (error) {
                console.error("Failed to check onboarding status:", error);
            }
        };
        void redirectSignedInUser();
        return () => { active = false; };
    }, [getToken, isLoaded, isSignedIn, router]);

    return (
        <div className="min-h-screen overflow-hidden bg-[#111820] text-slate-100">
            <header className="border-b border-slate-700/70 bg-[#141c26]/90 backdrop-blur-xl">
                <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
                    <a href="#top" className="flex items-center gap-2.5">
                        <span className="flex size-9 items-center justify-center rounded-lg border border-amber-300/35 bg-amber-300/10 text-amber-200"><Dices size={19} strokeWidth={1.5} /></span>
                        <span className="font-serif text-base font-bold tracking-tight text-stone-100">DnD Planner</span>
                    </a>
                    <div className="flex items-center gap-2 sm:gap-3">
                        <nav className="hidden items-center gap-5 text-[11px] font-semibold text-slate-400 md:flex">
                            <a href="#demo" className="transition hover:text-amber-100">See the demo</a>
                            <a href="#demo" className="transition hover:text-amber-100">Get started</a>
                        </nav>
                        <ThemeToggle />
                        <Show when="signed-out">
                            <SignInButton mode="modal"><button className="rounded-md px-2.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:text-amber-100 sm:px-3">Sign in</button></SignInButton>
                            <SignUpButton mode="modal"><button className="rounded-md border border-amber-200/40 bg-[#d5a75b] px-3 py-1.5 text-xs font-bold text-[#18140f] shadow-[0_5px_18px_rgba(213,167,91,0.18)] transition hover:bg-[#e4bc77] sm:px-4">Get started</button></SignUpButton>
                        </Show>
                        <Show when="signed-in"><button onClick={() => router.push("/app")} className="rounded-md border border-amber-200/40 bg-[#d5a75b] px-3 py-1.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77]">Open app</button><UserButton /></Show>
                    </div>
                </div>
            </header>

            <main id="top" className="relative">
                <div className="pointer-events-none absolute -right-24 top-[10rem] h-[22rem] w-[22rem] opacity-45 sm:-right-20 sm:top-[8rem] sm:h-[34rem] sm:w-[34rem] lg:-right-12 lg:top-[7rem] lg:h-[44rem] lg:w-[44rem]">
                    <HeroD20 />
                </div>
                <section className="relative z-10 mx-auto max-w-7xl px-4 pb-12 pt-16 sm:px-6 sm:pb-16 sm:pt-24">
                    <div className="pointer-events-none absolute left-1/2 top-4 size-[34rem] -translate-x-1/2 rounded-full border border-amber-200/[0.05] bg-[radial-gradient(circle,rgba(203,155,76,0.13),transparent_66%)]" />
                    <div className="relative mx-auto max-w-4xl text-center">
                        <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-amber-200/20 bg-amber-100/[0.04] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/80"><Dices size={13} /> Built for real campaign tables</p>
                        <h1 className="font-serif text-4xl font-bold leading-[1.05] tracking-tight text-stone-100 sm:text-6xl">Stop scheduling D&amp;D in <span className="text-[#e0b66e]">group chats.</span></h1>
                        <p className="mx-auto mt-5 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">Share availability, find the best date, schedule the session, and get playing.</p>
                        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
                            <Show when="signed-out"><SignUpButton mode="modal"><button className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-5 py-2.5 text-sm font-bold text-[#18140f] shadow-[0_8px_24px_rgba(213,167,91,0.18)] transition hover:bg-[#e4bc77] sm:w-auto">Start planning <ArrowRight size={16} /></button></SignUpButton></Show>
                            <Show when="signed-in"><button onClick={() => router.push("/app")} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-5 py-2.5 text-sm font-bold text-[#18140f] sm:w-auto">Open dashboard <ArrowRight size={16} /></button></Show>
                            <a href="#demo" className="w-full rounded-md border border-slate-600 bg-slate-800/60 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-slate-500 hover:bg-slate-800 sm:w-auto">Explore the demo</a>
                        </div>
                    </div>
                </section>

                <InteractiveGroupDemo />

            </main>
            <footer className="border-t border-slate-700/60 px-4 py-6 text-center text-[11px] text-slate-500">DnD Planner · Campaign scheduling without the chase</footer>
        </div>
    );
}

function HeroD20() {
    return (
        <svg viewBox="0 0 480 480" fill="none" aria-hidden="true" className="size-full">
            <defs>
                <radialGradient id="d20-glow" cx="50%" cy="43%" r="58%"><stop stopColor="#d5a75b" stopOpacity="0.18" /><stop offset="0.7" stopColor="#d5a75b" stopOpacity="0.035" /><stop offset="1" stopColor="#d5a75b" stopOpacity="0" /></radialGradient>
                <linearGradient id="d20-face" x1="95" y1="62" x2="392" y2="419" gradientUnits="userSpaceOnUse"><stop stopColor="#f0ca84" stopOpacity="0.16" /><stop offset="1" stopColor="#876330" stopOpacity="0.025" /></linearGradient>
            </defs>
            <circle cx="240" cy="240" r="218" fill="url(#d20-glow)" />
            <path d="M240 42 397 150 337 374 143 374 83 150 240 42Z" fill="url(#d20-face)" stroke="#e0b66e" strokeOpacity="0.4" strokeWidth="1.5" />
            <path d="m240 42 67 155-67 177-67-177L240 42Zm-157 108 90 47-30 177L83 150Zm314 0-90 47 30 177 60-224ZM143 374l97-177 97 177H143Z" stroke="#e0b66e" strokeOpacity="0.28" strokeWidth="1" />
            <path d="m83 150 157 47 157-47M143 374l97-177 97 177M173 197l67 177 67-177" stroke="#e0b66e" strokeOpacity="0.22" strokeWidth="1" />
            <path d="m143 374 97-177 97 177M83 150l90 47M397 150l-90 47" stroke="#f5d79a" strokeOpacity="0.16" strokeWidth="0.75" />
            <circle cx="240" cy="197" r="5" fill="#e0b66e" fillOpacity="0.24" />
        </svg>
    );
}
