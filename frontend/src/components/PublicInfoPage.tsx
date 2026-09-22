import Link from "next/link";
import type { ReactNode } from "react";

export function PrivacySupportLinks() {
    return <nav aria-label="Privacy and support" className="flex justify-center gap-5 text-xs text-slate-400">
        <Link href="/privacy" className="hover:text-amber-200 focus-visible:outline-amber-200">Privacy</Link>
        <Link href="/support" className="hover:text-amber-200 focus-visible:outline-amber-200">Support</Link>
    </nav>;
}

export default function PublicInfoPage({ title, children }: { title: string; children: ReactNode }) {
    return <div className="min-h-screen bg-[#111820] text-slate-100">
        <header className="border-b border-slate-700 px-5 py-4"><Link href="/" className="font-serif text-lg text-amber-200">DnD Planner</Link></header>
        <main className="mx-auto max-w-2xl space-y-6 px-5 py-10 text-sm leading-7 text-slate-300">
            <h1 className="font-serif text-3xl font-bold text-stone-100">{title}</h1>
            {children}
        </main>
        <footer className="border-t border-slate-700 px-5 py-6"><PrivacySupportLinks /></footer>
    </div>;
}
