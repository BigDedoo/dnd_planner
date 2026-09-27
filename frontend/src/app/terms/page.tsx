import Link from "next/link";
import PublicInfoPage from "@/components/PublicInfoPage";
import terms from "../../../../backend/terms.json";

export const metadata = { title: "Terms of Use | DnD Planner", description: "Terms for the free DnD Planner group-planning service." };

export default function TermsPage() {
    return <PublicInfoPage title="Terms of Use">
        <p className="text-xs text-slate-400">Version {terms.version} · Terms for the current free service</p>
        {terms.sections.map(section => <section key={section.title}><h2>{section.title}</h2>{section.paragraphs.map(text => <p key={text}>{text}</p>)}</section>)}
        <p><Link href="/legal">Legal Notice</Link> · <Link href="/privacy">Privacy Policy</Link> · <Link href="/support">Contact Support</Link></p>
    </PublicInfoPage>;
}
