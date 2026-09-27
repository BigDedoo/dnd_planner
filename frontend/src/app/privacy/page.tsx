import Link from "next/link";
import PublicInfoPage from "@/components/PublicInfoPage";
import { missingLegalDetail } from "@/lib/legal";
import { legalDetails } from "@/lib/legalConfig";

export const dynamic = "force-dynamic";
export const metadata = { title: "Privacy Policy | DnD Planner" };

export default function PrivacyPage() {
    const operator = legalDetails();
    return <PublicInfoPage title="Privacy Policy">
        <p className="text-xs text-slate-400">Last updated 26 September 2026 · Information, not a consent agreement</p>
        <section><h2>Who is responsible</h2><p>The DnD Planner operator is the controller of personal data used to run the planner: {operator.operatorName || missingLegalDetail}. See the <Link href="/legal">Legal Notice</Link> for identity and contact details. Use <Link href="/support#privacy-rights">Support</Link> for privacy questions and requests.</p></section>
        <section><h2>What the app processes</h2>
            <p>Clerk handles sign-in. DnD Planner receives a verified authentication identity and stores an internal account ID, provider identity link, and email, username and display name when supplied. A linked planner profile includes a display name and timezone. Account records also contain the version and time of explicit Terms acceptance.</p>
            <p>Planning records include groups, memberships and roles, group nicknames, global and group-specific day availability, availability-mode settings, scheduled dates and times, session titles and notes, RSVPs, hashed invite-code metadata and notification preferences. Email delivery and pending-message records support service communications.</p>
            <p>Operational and security logs may contain request/device information such as IP addresses, timestamps and errors. Information you send for technical support, content reports, account deletion or other data-rights requests is used to handle that request. Do not send passwords, sign-in tokens or invite codes to support.</p>
        </section>
        <section><h2>Purposes and legal bases</h2>
            <p>Account access, shared planning, invitations, exports and related service emails are processed to provide the service you request and perform the Terms of Use. Security, abuse prevention, troubleshooting and proportionate operational backups rely on legitimate interests in maintaining a safe, reliable service, balanced against your rights. Applicable legal obligations can require handling rights requests or retaining specific records.</p>
            <p>Consent is not the basis for all core processing. If a future optional use requires consent, it must be requested separately and can be withdrawn for that use. Accepting Terms does not authorize marketing. Planner data is not used here to make automated decisions with legal or similarly significant effects about you.</p>
        </section>
        <section><h2>Who can receive data</h2>
            <p>Your group members see shared planning content, effective nicknames, availability and session responses. Your account email is not included in group rosters. Group administrators exercise their defined management permissions. The operator accesses data as necessary for support, security and maintenance; lawful disclosures may also be required.</p>
            <p>Clerk processes authentication and account identity. OVH SAS provides the OVHcloud VPS infrastructure that hosts the application and database. The configured transactional email provider handles service email delivery, including recipient addresses and message contents. Restricted off-site backup copies are held on operator-controlled Raspberry Pi storage. If you choose an external identity provider or open a Google Calendar event link, that provider also receives information needed for the action under its own terms.</p>
        </section>
        <section><h2>International processing</h2>
            <p>Clerk may process personal data outside the European Economic Area. Its published <a href="https://clerk.com/legal/dpa">Data Processing Addendum</a> describes reliance on the EU–US Data Privacy Framework for applicable transfers while that framework remains valid and applicable. It provides for Standard Contractual Clauses when Clerk cannot rely on that framework for transfers within the scope of the GDPR. This does not mean every Clerk processing operation takes place in the United States.</p>
            <p>Other providers and their subprocessors may also process data outside the EEA. Their actual destinations and applicable safeguards depend on their arrangements with the operator. Contact <Link href="/support#privacy-rights">Support</Link> for information about transfers involving your data.</p>
        </section>
        <section><h2>Retention and leaving</h2>
            <p>Active account and planning records remain available while needed to operate your account and shared groups, subject to deletion requests and applicable obligations. There is no automatic general inactivity-deletion deadline implemented. Support, security logs and delivery records are kept as needed for their purposes; a fixed schedule for these records is not specified in this notice. Contact Support for details.</p>
            <p>Account deletion is operator-assisted after verification. Ownership of groups must first be transferred or the groups deleted. The process removes your account, memberships, global and group-specific availability, RSVPs and related personal records from the active app. Shared session history remains; when attribution is needed, your profile becomes “Deleted user” with direct identifiers cleared. Shared text is not automatically scanned for personal details: identify any concerns in your request. Clerk identity handling is a separate operator step.</p>
            <p>Routine VPS database backups are retained for 14 days and off-site Raspberry Pi copies for 90 days. Historical copies expire through their normal retention schedule rather than immediate individual-record erasure. Deployment safety backups are separate and not covered by daily pruning; contact Support for details about their retention. Completed deletion requests must be reapplied after restoring an older backup.</p>
        </section>
        <section><h2>Your rights and how to use them</h2>
            <p>Subject to applicable conditions, you can request access, correction, deletion, restriction, objection to processing based on legitimate interests, and portability. Where processing actually relies on consent, you can withdraw it without affecting earlier lawful processing. You may complain to the <a href="https://www.cnil.fr/fr/plaintes">CNIL</a>.</p>
            <p><Link href="/account">Account / Data</Link> provides a JSON export and deletion guidance. For other requests, use <Link href="/support#privacy-rights">Support — privacy rights</Link>, explain your request and provide a way to identify your account. Identity checks must be proportionate; never send a password. Requests are normally answered within one month; if an extension is lawfully needed, you will be told why. Legal information, account export and support remain available without accepting updated Terms.</p>
        </section>
        <section><h2>Security, storage and communications</h2>
            <p>Access controls, authenticated group permissions, encrypted transport and restricted backups help protect data; no system can promise absolute security. See <Link href="/cookies">Cookies & technical storage</Link> for authentication and interface preferences. The public demo uses fictional, in-memory data.</p>
            <p>Session scheduling, changes, cancellations and personal or missing-RSVP reminders are service communications, not marketing. Available email preferences are in Account / Data. The current service does not send marketing messages.</p>
        </section>
        <section><h2>Updates</h2><p>This notice may change as processing changes. The update date identifies this text; significant changes should be brought to your attention. You are not asked to accept the Privacy Policy.</p></section>
    </PublicInfoPage>;
}
