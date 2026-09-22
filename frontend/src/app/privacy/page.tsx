import Link from "next/link";
import PublicInfoPage from "@/components/PublicInfoPage";

export default function PrivacyPage() {
    return <PublicInfoPage title="Privacy & your data">
        <section><h2 className="text-lg font-semibold text-amber-100">What the app stores</h2>
            <p>Clerk handles sign-in. DnD Planner stores an internal account linked to that identity, including email, username and display name when provided, and your planner profile and timezone.</p>
            <p>Planning records include group memberships and nicknames, day availability, scheduled sessions and notes, RSVPs, invitation metadata (including hashed codes), and records of session notifications. Group members can see shared planning information; your account email is not included in group rosters.</p>
        </section>
        <section><h2 className="text-lg font-semibold text-amber-100">Why it is used</h2>
            <p>These records operate your account, coordinate groups and schedule sessions. Server and application logs support reliability, troubleshooting and account support. Database backups help recover the service after failures.</p>
        </section>
        <section><h2 className="text-lg font-semibold text-amber-100">Exporting data or leaving</h2>
            <p>Sign in and visit <Link href="/account" className="underline text-amber-200">Account / Data</Link> to download your personal application records as JSON or request help through <Link href="/support" className="underline text-amber-200">Support</Link>.</p>
            <p>Account deletion is handled by the operator after verifying your request. You must first transfer ownership of every group you own or delete those groups in their settings. Deletion is not immediate when you send a request.</p>
            <p>The process removes your account, memberships, availability, RSVPs and related personal records from the active app. Shared session history remains; where it needs an attribution record, your profile becomes “Deleted user” with its direct identifiers cleared. Shared session text is not automatically scanned for personal details; mention any such concerns in your request. Clerk account handling is a separate operator step.</p>
        </section>
        <section><h2 className="text-lg font-semibold text-amber-100">Backups</h2>
            <p>Deletion affects the active service first. Routine VPS database backups are retained for 14 days and off-site Raspberry Pi copies for 90 days. Those historical copies expire through their normal retention schedule, not immediate individual-record erasure.</p>
            <p>Deployment safety backups are separate and are not covered by daily backup pruning; the operator must review their retention separately. After restoring an older backup, completed deletion requests must be reapplied before the restored service is considered reconciled.</p>
        </section>
    </PublicInfoPage>;
}
