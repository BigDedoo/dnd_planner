import Link from "next/link";
import PublicInfoPage from "@/components/PublicInfoPage";

export const metadata = { title: "Cookies & Technical Storage | DnD Planner" };

export default function CookiesPage() {
    return <PublicInfoPage title="Cookies & technical storage">
        <section><h2>Sign-in and security</h2><p>DnD Planner is not cookie-free. Clerk uses cookies and browser storage to keep you signed in, refresh authentication, remember the active account and protect sign-in security. These are used for the service you request, not an advertising profile. Exact names and lifetimes depend on Clerk configuration; see <a href="https://clerk.com/docs/guides/how-clerk-works/cookies">Clerk’s cookie documentation</a>. A chosen external sign-in provider operates its own sign-in pages and storage.</p></section>
        <section><h2>Interface preference</h2><p>The browser’s local storage contains a “theme” preference for light or dark presentation. It remains until changed or cleared in the browser. The initial preference may use your device’s color-scheme setting. The public interactive demo uses only temporary in-memory state; reloading resets that demo.</p></section>
        <section><h2>Optional telemetry and analytics</h2><p>DnD Planner disables Clerk’s optional SDK usage telemetry through Clerk’s supported configuration. This does not disable sign-in or session security. The application does not currently include advertising pixels or behavioral analytics. See <a href="https://clerk.com/docs/guides/how-clerk-works/security/clerk-telemetry">Clerk’s telemetry documentation</a>.</p></section>
        <section><h2>Your controls</h2><p>You can sign out and clear site cookies or storage in your browser. Blocking authentication cookies can prevent sign-in; clearing local storage resets interface preferences. These actions do not delete your planner account or server-side data. For that, see <Link href="/account">Account / Data</Link> or <Link href="/support">Support</Link>.</p><p>See the <Link href="/privacy">Privacy Policy</Link> and the <a href="https://www.cnil.fr/fr/cookies-et-autres-traceurs/que-dit-la-loi">CNIL’s information on cookies and other trackers</a>.</p></section>
    </PublicInfoPage>;
}
