import PublicInfoPage from "@/components/PublicInfoPage";
import { legalDetails } from "@/lib/legalConfig";

export const dynamic = "force-dynamic";
export const metadata = { title: "Legal Notice | DnD Planner" };

export default function LegalPage() {
    const details = legalDetails();
    const publisherRows = [
        ["Publisher / data controller", details.operatorName],
        ["Legal status", details.operatorStatus],
        ["Postal address", details.operatorAddress],
        ["Telephone", details.operatorPhone],
        ["Contact", details.operatorContact],
        ["Publication director", details.publicationDirector],
    ];
    const missingPublisherDetails = publisherRows.filter(([, value]) => !value).map(([label]) => label?.toLowerCase());
    return <PublicInfoPage title="Legal Notice">
        <section><h2>Service</h2><p>DnD Planner is available at <a href="https://dnd-planner.dedoo.fr">https://dnd-planner.dedoo.fr</a>.</p></section>
        <section>
            <h2>Publisher and data controller</h2>
            {missingPublisherDetails.length > 0 && <p role="status" className="rounded-lg border border-amber-200/30 bg-amber-200/5 p-4">Publisher details require confirmation before this notice can be published: {missingPublisherDetails.join(", ")}.</p>}
            {publisherRows.some(([, value]) => value) && <dl className="mt-4 space-y-3">{publisherRows.filter(([, value]) => value).map(([label, value]) => <div key={label}><dt className="font-semibold text-stone-100">{label}</dt><dd className="whitespace-pre-line">{label === "Contact" ? <a href={value!}>{value}</a> : value}</dd></div>)}</dl>}
        </section>
        <section>
            <h2>Hosting provider</h2>
            <p>DnD Planner uses OVHcloud VPS infrastructure operated by OVH SAS.</p>
            <dl className="mt-4 space-y-3">
                <div><dt className="font-semibold text-stone-100">Legal form</dt><dd>Société par actions simplifiée (SAS)</dd></div>
                <div><dt className="font-semibold text-stone-100">Share capital</dt><dd>€50,000,000</dd></div>
                <div><dt className="font-semibold text-stone-100">Registration</dt><dd>RCS Lille Métropole 424 761 419 00045</dd></div>
                <div><dt className="font-semibold text-stone-100">Registered office</dt><dd>2 rue Kellermann<br />59100 Roubaix<br />France</dd></div>
                <div><dt className="font-semibold text-stone-100">Contact</dt><dd><a href="https://www.ovhcloud.com/fr/contact/">OVHcloud contact and support</a></dd></div>
            </dl>
            <p className="mt-4 text-xs text-slate-400">Provider details: <a href="https://www.ovhcloud.com/fr/terms-and-conditions/">OVHcloud legal notice</a>.</p>
        </section>
    </PublicInfoPage>;
}
