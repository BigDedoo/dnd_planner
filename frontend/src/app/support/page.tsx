import PublicInfoPage from "@/components/PublicInfoPage";
import { supportContactUrl } from "@/lib/supportContact";

// Read server-only configuration at request time, including in standalone Docker.
export const dynamic = "force-dynamic";

export default function SupportPage() {
    const contact = supportContactUrl(process.env.SUPPORT_CONTACT_URL);
    return <PublicInfoPage title="Support">
        <p>Contact the operator for technical help, account or data questions, or an account deletion request.</p>
        <section className="rounded-xl border border-slate-700 bg-[#1a232e] p-5">
            {contact ? <a href={contact} className="inline-flex rounded-md bg-[#d5a75b] px-4 py-2 font-semibold text-[#18140f] hover:bg-[#e4bc77]">Contact support</a>
                : <p role="status">Support contact is not configured yet.</p>}
        </section>
        <section id="account-deletion"><h2 className="text-lg font-semibold text-amber-100">Request account deletion</h2>
            <p>First transfer ownership or delete any groups you own in Group Settings. Then contact support, state that you want your DnD Planner account and personal data deleted, and include the Account ID shown on Account / Data. The operator will independently verify that you hold the account before proceeding.</p>
            <p>Sending a request does not delete anything immediately. Do not send passwords, sign-in tokens or invite codes. The operator will confirm completion and handle the Clerk identity separately.</p>
        </section>
    </PublicInfoPage>;
}
