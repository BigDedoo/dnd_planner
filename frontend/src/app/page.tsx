"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { ArrowRight, CalendarCheck2, CalendarDays, Check, ChevronLeft, ChevronRight, Dices, UsersRound } from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { fetchOnboardingStatus } from "@/services/api";

const previewWeekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const previewCalendarDays = [
    null,
    null,
    null,
    { day: 1 },
    { day: 2 },
    { day: 3 },
    { day: 4 },
    { day: 5 },
    { day: 6 },
    { day: 7 },
    { day: 8, availability: "4/5", tone: "green" },
    { day: 9, availability: "4/5", tone: "green" },
    { day: 10, availability: "3/5", tone: "amber" },
    { day: 11 },
    { day: 12 },
    { day: 13 },
    { day: 14 },
    { day: 15, availability: "5/5", tone: "green" },
    { day: 16, availability: "4/5", tone: "green" },
    { day: 17, availability: "4/5", tone: "green" },
    { day: 18 },
    { day: 19, availability: "5/5", tone: "green", confirmed: true },
    { day: 20 },
    { day: 21 },
    { day: 22 },
    { day: 23, availability: "3/5", tone: "amber" },
    { day: 24 },
    { day: 25 },
    { day: 26 },
    { day: 27 },
    { day: 28 },
    { day: 29 },
    { day: 30 },
    { day: 31 },
    null,
];

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
                        <nav className="hidden items-center gap-5 text-[11px] font-semibold text-slate-400 md:flex"><a href="#features" className="transition hover:text-amber-100">Features</a><a href="#preview" className="transition hover:text-amber-100">How it works</a></nav>
                        <ThemeToggle />
                        <Show when="signed-out"><SignInButton mode="modal"><button className="rounded-md px-2.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:text-amber-100 sm:px-3">Sign in</button></SignInButton><SignUpButton mode="modal"><button className="rounded-md border border-amber-200/40 bg-[#d5a75b] px-3 py-1.5 text-xs font-bold text-[#18140f] shadow-[0_5px_18px_rgba(213,167,91,0.18)] transition hover:bg-[#e4bc77] sm:px-4">Get started</button></SignUpButton></Show>
                        <Show when="signed-in"><button onClick={() => router.push("/app")} className="rounded-md border border-amber-200/40 bg-[#d5a75b] px-3 py-1.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77]">Open app</button><UserButton /></Show>
                    </div>
                </div>
            </header>

            <main id="top" className="relative">
                <div className="pointer-events-none absolute -right-24 top-[12rem] h-[22rem] w-[22rem] opacity-50 sm:-right-20 sm:top-[11rem] sm:h-[34rem] sm:w-[34rem] lg:-right-12 lg:top-[8rem] lg:h-[44rem] lg:w-[44rem]">
                    <HeroD20 />
                </div>
                <section className="relative z-10 mx-auto max-w-7xl px-4 pb-14 pt-16 sm:px-6 sm:pt-24">
                    <div className="pointer-events-none absolute left-1/2 top-4 size-[34rem] -translate-x-1/2 rounded-full border border-amber-200/[0.05] bg-[radial-gradient(circle,rgba(203,155,76,0.13),transparent_66%)]" />
                    <div className="relative mx-auto max-w-4xl text-center">
                        <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-amber-200/20 bg-amber-100/[0.04] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/80"><Dices size={13} /> Built for real campaign tables</p>
                        <h1 className="font-serif text-4xl font-bold leading-[1.05] tracking-tight text-stone-100 sm:text-6xl">Make a date for the next <span className="text-[#e0b66e]">great session.</span></h1>
                        <p className="mx-auto mt-5 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">A calm place for groups to share availability, lock in sessions, and keep every campaign on the same calendar.</p>
                        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
                            <Show when="signed-out"><SignUpButton mode="modal"><button className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-5 py-2.5 text-sm font-bold text-[#18140f] shadow-[0_8px_24px_rgba(213,167,91,0.18)] transition hover:bg-[#e4bc77] sm:w-auto">Create your group <ArrowRight size={16} /></button></SignUpButton></Show>
                            <Show when="signed-in"><button onClick={() => router.push("/app")} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-5 py-2.5 text-sm font-bold text-[#18140f] sm:w-auto">Open dashboard <ArrowRight size={16} /></button></Show>
                            <a href="#preview" className="w-full rounded-md border border-slate-600 bg-slate-800/60 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-slate-500 hover:bg-slate-800 sm:w-auto">See the calendar</a>
                        </div>
                    </div>
                </section>

                <section id="preview" className="relative z-10 mx-auto max-w-7xl px-4 pb-16 sm:px-6">
                    <div className="overflow-hidden rounded-xl border border-slate-600/80 bg-[#18212c] shadow-[0_24px_70px_rgba(0,0,0,0.42)]">
                        <div className="flex items-center justify-between border-b border-slate-700/70 bg-[#202a36] px-3 py-2.5 sm:px-4"><div className="flex items-center gap-2 text-xs font-bold text-slate-200"><span className="size-2 rounded-full bg-emerald-400" /> The party is planning</div><span className="rounded border border-slate-600 bg-[#161e28] px-2 py-1 text-[10px] text-slate-400">Calendar preview</span></div>
                        <div className="grid min-h-[410px] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_250px]">
                            <div className="p-3 sm:p-5">
                                <div className="mb-4 flex items-center justify-between gap-3"><div><div className="flex items-center gap-2"><CalendarDays size={17} className="text-amber-200" /><p className="font-serif text-base font-bold text-stone-100">Group Calendar</p></div><p className="mt-1 text-[10px] text-slate-500">Availability at a glance</p></div><div className="flex items-center rounded-md border border-slate-600 bg-[#151d27] p-0.5 text-xs text-slate-300"><ChevronLeft size={14} className="mx-1" /><span className="border-x border-slate-600 px-2.5 py-1 font-semibold">Campaign month</span><ChevronRight size={14} className="mx-1" /></div></div>
                                <div className="grid grid-cols-7 gap-1.5 sm:gap-2">{previewWeekdays.map((day) => <div key={day} className="pb-1 text-center text-[9px] font-bold uppercase tracking-wide text-slate-500">{day}</div>)}{previewCalendarDays.map((entry, index) => entry ? <div key={entry.day} className={`relative min-h-[58px] rounded-md border p-1.5 sm:min-h-[76px] sm:p-2 ${entry.confirmed ? "border-amber-200/70 bg-amber-200/[0.10] shadow-[inset_0_0_0_1px_rgba(213,167,91,0.15)]" : entry.tone === "green" ? "border-emerald-400/15 bg-emerald-400/[0.06]" : entry.tone === "amber" ? "border-amber-300/15 bg-amber-300/[0.07]" : "border-slate-700/80 bg-[#202a36]/75"}`}><span className="text-[10px] font-semibold text-slate-300">{entry.day}</span>{entry.availability && <><p className={`mt-1 text-center text-sm font-bold sm:text-base ${entry.tone === "amber" ? "text-amber-200" : "text-emerald-300"}`}>{entry.availability}</p><div className="mt-1 flex justify-center gap-0.5">{Array.from({ length: 5 }, (_, dotIndex) => <span key={dotIndex} className={`size-1.5 rounded-full ${dotIndex < Number(entry.availability[0]) ? entry.tone === "amber" ? "bg-amber-300" : "bg-emerald-400" : "bg-slate-600"}`} />)}</div></>}{entry.confirmed && <span className="absolute bottom-1.5 left-1.5 right-1.5 truncate rounded border border-amber-200/20 bg-[#d5a75b]/15 px-1 py-0.5 text-center text-[8px] font-bold uppercase tracking-wide text-amber-100">Session</span>}</div> : <div key={`empty-${index}`} className="min-h-[58px] rounded-md border border-transparent bg-[#141c26]/35 sm:min-h-[76px]" />)}</div>
                            </div>
                            <aside className="relative overflow-hidden border-t border-slate-700/70 bg-[#151d27] p-4 lg:border-l lg:border-t-0"><div className="pointer-events-none absolute -right-8 -top-7 flex size-32 items-center justify-center rounded-full border border-amber-200/10 text-4xl text-amber-200/[0.06]">✦</div><div className="relative"><p className="text-[10px] font-bold uppercase tracking-wider text-amber-200/70">Selected day</p><p className="mt-1 font-serif text-lg font-bold text-stone-100">Day 19</p><div className="mt-4 rounded-md border border-amber-200/25 bg-amber-200/[0.09] px-3 py-2 text-xs font-bold text-amber-100">✓ Session confirmed</div><p className="mt-5 text-[10px] font-bold uppercase tracking-wider text-slate-500">Party availability</p><div className="mt-2 space-y-2">{["Player one", "Player two", "Player three", "Player four", "You"].map((player) => <div key={player} className="flex items-center justify-between border-b border-slate-700/60 pb-2 text-xs"><span className="text-slate-300">{player}</span><span className="flex items-center gap-1 text-emerald-300"><Check size={12} /> Available</span></div>)}</div></div></aside>
                        </div>
                    </div>
                </section>

                <section id="features" className="border-y border-slate-700/60 bg-[#151d27] py-14">
                    <div className="mx-auto grid max-w-6xl gap-5 px-4 sm:grid-cols-3 sm:px-6">
                        <FeatureCard icon={<UsersRound size={19} />} title="Campaign groups">
                            <CampaignGroupsPreview />
                        </FeatureCard>
                        <FeatureCard icon={<CalendarCheck2 size={19} />} title="Confirmed sessions">
                            <ConfirmedSessionPreview />
                        </FeatureCard>
                        <FeatureCard icon={<CalendarDays size={19} />} title="My Schedule">
                            <MySchedulePreview />
                        </FeatureCard>
                    </div>
                </section>
            </main>
            <footer className="border-t border-slate-700/60 px-4 py-6 text-center text-[11px] text-slate-500">DnD Planner · Campaign scheduling without the chase</footer>
        </div>
    );
}

function FeatureCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
    return <div className="rounded-lg border border-slate-700/70 bg-[#1a232e] p-5 shadow-[0_18px_35px_rgba(5,9,14,0.16)]"><div className="mb-4 flex items-center gap-3"><span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-amber-200/20 bg-amber-200/[0.06] text-amber-200">{icon}</span><h2 className="font-serif text-lg font-bold text-stone-100">{title}</h2></div>{children}</div>;
}

function CampaignGroupsPreview() {
    const members = [{ name: "Player one", status: "Available", tone: "text-emerald-300" }, { name: "Player two", status: "Maybe", tone: "text-amber-200" }, { name: "Player three", status: "Available", tone: "text-emerald-300" }];
    return <div className="overflow-hidden rounded-md border border-slate-700/80 bg-[#111821] text-xs"><div className="flex items-center justify-between border-b border-slate-700/70 px-3 py-2.5"><div><p className="font-medium text-stone-100">Campaign group</p><p className="mt-0.5 text-[10px] text-slate-500">5 adventurers</p></div><span className="rounded border border-amber-200/20 bg-amber-200/[0.08] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-amber-200">OWNER</span></div><div className="space-y-1.5 p-2.5">{members.map((member, index) => <div key={member.name} className="flex items-center justify-between rounded bg-slate-800/60 px-2 py-1.5"><span className="flex min-w-0 items-center gap-2 text-slate-200"><span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-slate-700 text-[8px] text-slate-400">{index + 1}</span>{member.name}</span><span className={`text-[10px] font-medium ${member.tone}`}>{member.status}</span></div>)}</div></div>;
}

function ConfirmedSessionPreview() {
    return <div className="overflow-hidden rounded-md border border-slate-700/80 bg-[#111821] p-3 text-xs"><div className="mb-2 flex items-center justify-between"><p className="font-medium text-stone-100">August 2026</p><span className="text-[10px] text-slate-500">Group calendar</span></div><div className="grid grid-cols-5 gap-1.5">{[20, 21, 22, 23, 24].map((day) => <div key={day} className={`flex h-11 flex-col justify-between rounded border px-1.5 py-1 ${day === 22 ? "border-amber-200/70 bg-amber-200/15 text-amber-100 shadow-[inset_0_0_0_1px_rgba(244,205,129,0.12)]" : "border-slate-700/70 bg-slate-800/60 text-slate-400"}`}><span>{day}</span>{day === 22 && <Check className="self-end text-amber-200" size={13} strokeWidth={3} />}</div>)}</div><div className="mt-3 flex items-center gap-2 rounded border border-amber-200/15 bg-amber-200/[0.06] px-2.5 py-2"><span className="flex size-5 items-center justify-center rounded-full bg-amber-200/15 text-amber-200"><Check size={12} strokeWidth={3} /></span><div><p className="font-medium text-amber-100">Session confirmed</p><p className="mt-0.5 text-[10px] text-slate-400">Campaign group</p></div></div></div>;
}

function MySchedulePreview() {
    const sessions = [{ day: "AUG 22", group: "Campaign group", status: "Available", tone: "text-emerald-300" }, { day: "AUG 28", group: "Second group", status: "Maybe", tone: "text-amber-200" }];
    return <div className="overflow-hidden rounded-md border border-slate-700/80 bg-[#111821] text-xs"><div className="border-b border-slate-700/70 px-3 py-2.5"><p className="font-medium text-stone-100">Upcoming</p></div><div className="divide-y divide-slate-700/60">{sessions.map((session) => <div key={session.day} className="flex items-center gap-3 px-3 py-3"><div className="w-10 shrink-0 text-center"><p className="font-semibold text-amber-200">{session.day.split(" ")[1]}</p><p className="text-[9px] font-medium tracking-wide text-slate-500">{session.day.split(" ")[0]}</p></div><div className="min-w-0 flex-1"><p className="truncate font-medium text-slate-100">{session.group}</p><p className={`mt-0.5 text-[10px] font-medium ${session.tone}`}>{session.status}</p></div><span className="size-1.5 shrink-0 rounded-full bg-amber-200/80" /></div>)}</div></div>;
}

function HeroD20() {
    return (
        <svg viewBox="0 0 480 480" fill="none" aria-hidden="true" className="size-full">
            <defs>
                <radialGradient id="d20-glow" cx="50%" cy="43%" r="58%">
                    <stop stopColor="#d5a75b" stopOpacity="0.18" />
                    <stop offset="0.7" stopColor="#d5a75b" stopOpacity="0.035" />
                    <stop offset="1" stopColor="#d5a75b" stopOpacity="0" />
                </radialGradient>
                <linearGradient id="d20-face" x1="95" y1="62" x2="392" y2="419" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#f0ca84" stopOpacity="0.16" />
                    <stop offset="1" stopColor="#876330" stopOpacity="0.025" />
                </linearGradient>
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
