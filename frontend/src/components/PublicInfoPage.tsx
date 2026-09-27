import Link from "next/link";
import type { ReactNode } from "react";
import LegalLinks from "@/components/LegalLinks";
import { independentDisclaimer } from "@/lib/legal";

export function PrivacySupportLinks() {
    return <LegalLinks />;
}

export default function PublicInfoPage({ title, children }: { title: string; children: ReactNode }) {
    return <div className="min-h-screen bg-[#111820] text-slate-100">
        <header className="border-b border-slate-700 px-5 py-4"><Link href="/" className="font-serif text-lg text-amber-200">DnD Planner</Link></header>
        <main className="mx-auto max-w-2xl space-y-6 break-words px-5 py-10 text-sm leading-7 text-slate-300 [&_h2]:mb-2 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-amber-100 [&_p+p]:mt-3 [&_a]:text-amber-200 [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5">
            <h1 className="font-serif text-3xl font-bold text-stone-100">{title}</h1>
            {children}
        </main>
        <footer className="border-t border-slate-700 px-5 py-6"><LegalLinks /><p className="mx-auto mt-4 max-w-2xl text-center text-xs leading-5 text-slate-500">{independentDisclaimer}</p></footer>
    </div>;
}
