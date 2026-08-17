"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import { Sparkles } from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { AppBrand } from "@/components/AppShell";
import { completeOnboarding, fetchOnboardingStatus } from "@/services/api";
import { safeOnboardingNext } from "@/lib/onboarding";

export default function OnboardingPage() {
    return (
        <Suspense fallback={<div className="min-h-screen bg-slate-50 dark:bg-slate-950" />}>
            <OnboardingForm />
        </Suspense>
    );
}

function OnboardingForm() {
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();
    const [displayName, setDisplayName] = useState("");
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const nextPath = safeOnboardingNext(searchParams.get("next"));

    useEffect(() => {
        let active = true;
        const loadStatus = async () => {
            if (!isLoaded) return;
            try {
                const token = await getToken();
                const status = await fetchOnboardingStatus(token);
                if (!active) return;
                if (status.linked) {
                    router.replace(nextPath);
                    return;
                }
                setDisplayName(status.suggested_display_name || "");
            } catch (err) {
                if (active) {
                    console.error("Failed to load onboarding:", err);
                    setError("We could not prepare your DnD Planner profile.");
                }
            } finally {
                if (active) setIsLoading(false);
            }
        };
        void loadStatus();
        return () => { active = false; };
    }, [getToken, isLoaded, nextPath, router]);

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!displayName.trim()) {
            setError("Choose a display name to continue.");
            return;
        }
        try {
            setIsSubmitting(true);
            setError(null);
            const token = await getToken();
            await completeOnboarding(displayName, token);
            router.replace(nextPath);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not create your profile.");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#111820] text-slate-100">
            <header className="border-b border-slate-700/70 bg-[#141c26]/95 backdrop-blur-xl">
                <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-6">
                    <AppBrand />
                    <div className="flex items-center gap-3"><ThemeToggle /><UserButton /></div>
                </div>
            </header>
            <main className="mx-auto flex min-h-[calc(100vh-56px)] max-w-md items-center px-6">
                <form onSubmit={handleSubmit} className="w-full rounded-xl border border-slate-700/80 bg-[#1a232e] p-7 shadow-[0_20px_45px_rgba(0,0,0,0.28)]">
                    <div className="mb-6 flex size-11 items-center justify-center rounded-lg border border-amber-200/25 bg-amber-200/10 text-amber-200"><Sparkles size={21} /></div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/65">One last step</p>
                    <h1 className="mt-1 font-serif text-3xl font-bold text-stone-100">Welcome to DnD Planner</h1>
                    <p className="mt-2 text-sm text-slate-400">Choose the name you use across DnD Planner. You can set a different nickname in each group later.</p>
                    <label className="mt-6 block text-xs font-bold text-slate-200">
                        Display name
                        <input autoFocus value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={120} className="mt-1.5 w-full rounded-md border border-slate-600 bg-[#111820] px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-amber-200/70" />
                    </label>
                    {error && <p className="mt-4 text-xs font-semibold text-rose-600 dark:text-rose-300">{error}</p>}
                    <button disabled={isLoading || isSubmitting} className="mt-6 w-full rounded-md bg-[#d5a75b] px-4 py-2.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60">
                        {isSubmitting ? "Creating profile..." : "Continue"}
                    </button>
                </form>
            </main>
        </div>
    );
}
