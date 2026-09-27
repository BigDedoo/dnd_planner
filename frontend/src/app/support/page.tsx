import PublicInfoPage from "@/components/PublicInfoPage";
import { supportContactUrl } from "@/lib/supportContact";

// Read server-only configuration at request time, including in standalone Docker.
export const dynamic = "force-dynamic";
export const metadata = { title: "Support & Reporting | DnD Planner" };

export default function SupportPage() {
    const contact = supportContactUrl(process.env.SUPPORT_CONTACT_URL);
    const emailContact = contact?.startsWith("mailto:") ? contact : null;
    const email = emailContact?.slice("mailto:".length);
    return <PublicInfoPage title="Support">
        <p>Use the contact below for technical support, account/data questions, privacy rights, account deletion or illegal/abusive-content reports. It is the same operator contact channel, not a public ticket board.</p>
        <div className="space-y-1">
            {email && emailContact ? <><p className="text-xs text-slate-400">Support contact</p><a href={emailContact} className="text-amber-200 underline decoration-amber-200/60 underline-offset-4 hover:text-amber-100">{email}</a></>
                : contact ? <><p className="text-xs text-slate-400">Support contact</p><a href={contact} className="text-amber-200 underline decoration-amber-200/60 underline-offset-4 hover:text-amber-100">Open support page</a></>
                : <p role="status">Support contact is not configured yet.</p>}
        </div>
        <section id="technical-help"><h2>Technical support and account questions</h2><p>Describe what happened, the page involved, your browser and the approximate time. Redact screenshots and logs before sending them. Do not include passwords, sign-in tokens, invite codes or other people’s private group content unnecessarily.</p></section>
        <section id="privacy-rights"><h2>Privacy and data-rights requests</h2><p>Tell the operator which right you want to exercise, the records concerned and how to contact you. Access, correction, deletion, restriction, objection and portability depend on applicable conditions. Account / Data offers a JSON export. Verification may be needed, but you do not need to accept updated Terms to contact us or request/export your data.</p></section>
        <section id="account-deletion"><h2 className="text-lg font-semibold text-amber-100">Request account deletion</h2>
            <p>First transfer ownership or delete any groups you own in Group Settings. Then contact support, state that you want your DnD Planner account and personal data deleted, and include the Account ID shown on Account / Data. The operator will independently verify that you hold the account before proceeding.</p>
            <p>If you do not accept updated Terms and cannot use Group Settings, contact Support directly to arrange ownership resolution and deletion. You do not have to accept new Terms to make a request.</p>
            <p>Sending a request does not delete anything immediately. Do not send passwords, sign-in tokens or invite codes. The operator will confirm completion and handle the Clerk identity separately.</p>
        </section>
        <section id="report-content"><h2>Report illegal or abusive content</h2><p>Contact Support privately with the exact location when possible: the relevant group or session link, or another identifier that lets the operator find the content. Explain why you believe it is illegal or abusive and include enough facts, context or evidence to assess the report. Add contact details if you want a response or the operator may need to ask a follow-up question. Do not publish private group content or share invite codes in a report. Reports are assessed by the operator; submitting one does not itself prove a violation.</p></section>
    </PublicInfoPage>;
}
