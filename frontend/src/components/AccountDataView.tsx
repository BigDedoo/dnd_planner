import Link from "next/link";
import type { AccountInfo, MyGroup } from "@/services/api";
import { SurfacePanel } from "@/components/AppShell";
import LegalLinks from "@/components/LegalLinks";

export default function AccountDataView({ account, groups, exporting, onExport }: {
    account: AccountInfo; groups: MyGroup[]; exporting: boolean; onExport: () => void;
}) {
    const ownedGroups = groups.filter(group => group.role === "owner");
    return <>
        <SurfacePanel className="space-y-2 p-5">
            <h2 className="font-serif text-xl text-stone-100">Account information</h2>
            <p>{account.display_name || account.username || "Your account"}</p>
            {account.username && <p className="text-sm text-slate-400">Username: {account.username}</p>}
            {account.email && <p className="break-words text-sm text-slate-400">Email: {account.email}</p>}
            <p className="break-all text-xs text-slate-400">Account ID: {account.id}</p>
        </SurfacePanel>
        <SurfacePanel className="space-y-3 p-5">
            <h2 className="font-serif text-xl text-stone-100">Terms & privacy rights</h2>
            <p className="text-sm text-slate-400">{account.terms_accepted ? `Current Terms accepted: ${account.terms_version}` : "The current Terms have not been accepted. Your account information, export, email preferences and support remain accessible."}</p>
            {account.terms_accepted_at && <p className="text-xs text-slate-400">Last agreement: {account.terms_version} · {new Date(account.terms_accepted_at).toLocaleString()}</p>}
            {!account.terms_accepted && <Link href="/onboarding?next=/account" className="inline-block text-sm text-amber-200 underline">Review current Terms</Link>}
            <p className="text-sm"><Link href="/support#privacy-rights" className="text-amber-200 underline">Contact the operator about your privacy rights</Link></p>
            <LegalLinks />
        </SurfacePanel>
        <SurfacePanel className="space-y-3 p-5">
            <h2 className="font-serif text-xl text-stone-100">Export my data</h2>
            <p className="text-sm text-slate-400">Download your account, profile, memberships, availability, RSVPs and related personal records as JSON.</p>
            <button onClick={onExport} disabled={exporting} className="rounded-md bg-[#d5a75b] px-4 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50">{exporting ? "Preparing download…" : "Download my data"}</button>
        </SurfacePanel>
        <SurfacePanel className="space-y-3 p-5">
            <h2 className="font-serif text-xl text-stone-100">Delete my account / data</h2>
            <p className="text-sm text-slate-400">Deletion is operator-assisted and requires verification. A support request does not immediately delete your account.</p>
            {!account.terms_accepted && <p className="text-sm text-slate-400">If you own a group and do not want to accept the Terms, contact Support to arrange ownership resolution. This page does not load group details before acceptance.</p>}
            {ownedGroups.length > 0 ? <>
                <p className="text-sm text-amber-200">Before deletion can proceed, transfer ownership or delete these groups in their settings:</p>
                <ul className="space-y-2">{ownedGroups.map(group => <li key={group.id}><Link href={`/groups/${group.id}/settings`} className="text-sm text-amber-200 underline">{group.name} · Settings</Link></li>)}</ul>
            </> : <Link href="/support#account-deletion" className="inline-block text-sm font-semibold text-amber-200 underline">Request account deletion</Link>}
        </SurfacePanel>
    </>;
}
