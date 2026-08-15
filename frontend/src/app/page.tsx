"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { CalendarDays, Shield, Sparkles, Users } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function LandingPage() {
    const { isSignedIn, isLoaded } = useAuth();
    const router = useRouter();

    useEffect(() => {
        if (isLoaded && isSignedIn) {
            router.replace("/app");
        }
    }, [isLoaded, isSignedIn, router]);

    return (
        <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col">
            {/* Top Navigation */}
            <header className="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
                <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="size-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 text-xl font-bold">
                            🎲
                        </div>
                        <div>
                            <span className="font-extrabold text-lg tracking-tight">DnD Planner</span>
                            <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300">
                                Phase 2B
                            </span>
                        </div>
                    </div>

                    <div className="flex items-center gap-3">
                        <ThemeToggle />
                        <div className="h-6 w-px bg-slate-200 dark:bg-slate-800" />
                        <Show when="signed-out">
                            <SignInButton mode="modal">
                                <button className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 transition shadow-sm">
                                    Sign in
                                </button>
                            </SignInButton>
                            <SignUpButton mode="modal">
                                <button className="cursor-pointer rounded-lg bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 transition shadow-md shadow-blue-600/20">
                                    Sign up
                                </button>
                            </SignUpButton>
                        </Show>
                        <Show when="signed-in">
                            <button
                                onClick={() => router.push("/app")}
                                className="cursor-pointer rounded-lg bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 transition shadow-sm"
                            >
                                Go to App
                            </button>
                            <UserButton />
                        </Show>
                    </div>
                </div>
            </header>

            {/* Hero Section */}
            <main className="flex-1 flex items-center justify-center p-6">
                <div className="max-w-3xl w-full text-center py-12">
                    <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 text-xs font-semibold mb-6">
                        <Sparkles size={14} /> Group Availability & Scheduling
                    </div>

                    <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">
                        Coordinate tabletop quests <br />
                        <span className="bg-gradient-to-r from-blue-600 to-indigo-500 bg-clip-text text-transparent">
                            without the scheduling curse.
                        </span>
                    </h1>

                    <p className="text-base sm:text-lg text-slate-600 dark:text-slate-300 mb-8 max-w-xl mx-auto">
                        Mark your dates as <span className="font-semibold text-emerald-600 dark:text-emerald-400">Available</span>, <span className="font-semibold text-amber-600 dark:text-amber-400">Maybe</span>, or <span className="font-semibold text-rose-600 dark:text-rose-400">No</span>, and instantly find the best dates for your campaign.
                    </p>

                    <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
                        <Show when="signed-out">
                            <SignUpButton mode="modal">
                                <button className="cursor-pointer w-full sm:w-auto px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition shadow-lg shadow-blue-600/25">
                                    Get Started
                                </button>
                            </SignUpButton>
                            <SignInButton mode="modal">
                                <button className="cursor-pointer w-full sm:w-auto px-6 py-3 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 font-semibold text-sm transition shadow-sm">
                                    Sign In to Your Account
                                </button>
                            </SignInButton>
                        </Show>
                        <Show when="signed-in">
                            <button
                                onClick={() => router.push("/app")}
                                className="cursor-pointer px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition shadow-lg shadow-blue-600/25"
                            >
                                Open My Groups Dashboard &rarr;
                            </button>
                        </Show>
                    </div>

                    {/* Features overview */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 text-left">
                        <div className="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
                            <div className="size-10 rounded-xl bg-blue-100 dark:bg-blue-950 flex items-center justify-center text-blue-600 dark:text-blue-400 mb-3">
                                <Users size={20} />
                            </div>
                            <h3 className="font-bold text-sm mb-1">Authenticated Groups</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                                Access campaign workspaces tied securely to your verified account.
                            </p>
                        </div>

                        <div className="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
                            <div className="size-10 rounded-xl bg-indigo-100 dark:bg-indigo-950 flex items-center justify-center text-indigo-600 dark:text-indigo-400 mb-3">
                                <CalendarDays size={20} />
                            </div>
                            <h3 className="font-bold text-sm mb-1">Live Group Calendars</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                                Interactive monthly matrices showing when everyone can play.
                            </p>
                        </div>

                        <div className="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
                            <div className="size-10 rounded-xl bg-emerald-100 dark:bg-emerald-950 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-3">
                                <Shield size={20} />
                            </div>
                            <h3 className="font-bold text-sm mb-1">Role-Based Access</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                                Group owners manage sessions while members update their own schedules.
                            </p>
                        </div>
                    </div>
                </div>
            </main>

            {/* Footer */}
            <footer className="border-t border-slate-200 dark:border-slate-800 py-6 text-center text-xs text-slate-400">
                DnD Planner &bull; Tabletop Campaign Scheduling
            </footer>
        </div>
    );
}
