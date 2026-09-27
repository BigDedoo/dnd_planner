import Link from "next/link";
import { legalLinks } from "@/lib/legal";

export default function LegalLinks() {
    return <nav aria-label="Legal information" className="flex flex-wrap justify-center gap-x-5 gap-y-3 text-xs text-slate-400">
        {legalLinks.map(([href, title]) => <Link key={href} href={href} className="rounded hover:text-amber-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-200">{title}</Link>)}
    </nav>;
}
