import Link from "next/link";
import type { AccountInfo, MyGroup } from "@/services/api";
import { SurfacePanel } from "@/components/AppShell";

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
            <h2 className="font-serif text-xl text-stone-100">Export my data</h2>
            <p className="text-sm text-slate-400">Download your account, profile, memberships, availability, RSVPs and related personal records as JSON.</p>
            <button onClick={onExport} disabled={exporting} className="rounded-md bg-[#d5a75b] px-4 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50">{exporting ? "Preparing download…" : "Download my data"}</button>
        </SurfacePanel>
        <SurfacePanel className="space-y-3 p-5">
            <h2 className="font-serif text-xl text-stone-100">Delete my account / data</h2>
            <p className="text-sm text-slate-400">Deletion is operator-assisted and requires verification. A support request does not immediately delete your account.</p>
            {ownedGroups.length > 0 ? <>
                <p className="text-sm text-amber-200">Before deletion can proceed, transfer ownership or delete these groups in their settings:</p>
                <ul className="space-y-2">{ownedGroups.map(group => <li key={group.id}><Link href={`/groups/${group.id}/settings`} className="text-sm text-amber-200 underline">{group.name} · Settings</Link></li>)}</ul>
            </> : <Link href="/support#account-deletion" className="inline-block text-sm font-semibold text-amber-200 underline">Request account deletion</Link>}
        </SurfacePanel>
    </>;
}
