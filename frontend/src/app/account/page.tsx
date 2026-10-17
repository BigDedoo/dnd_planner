"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { AppHeader } from "@/components/AppShell";
import AccountDataView from "@/components/AccountDataView";
import MembershipSettings, { type CheckoutReturn } from "@/components/MembershipSettings";
import SessionReminderSettings from "@/components/SessionReminderSettings";
import { PrivacySupportLinks } from "@/components/PublicInfoPage";
import { downloadMyData, fetchCurrentAccount, fetchMyGroups, fetchOnboardingStatus, type AccountInfo, type MyGroup } from "@/services/api";

export default function AccountPage() {
    const { getToken, isLoaded } = useAuth();
    const [data, setData] = useState<{ account: AccountInfo; groups: MyGroup[]; linked: boolean } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [exporting, setExporting] = useState(false);
    // Only rendered after client-side loading, so reading the URL here cannot mismatch hydration.
    const [checkoutReturn] = useState<CheckoutReturn>(() => {
        if (typeof window === "undefined") return null;
        const params = new URLSearchParams(window.location.search);
        if (params.get("support") === "thanks") return "gift";
        const value = params.get("membership");
        return value === "success" || value === "cancelled" ? value : null;
    });
    useEffect(() => {
        if (!isLoaded) return;
        let active = true;
        void (async () => {
            try {
                const token = await getToken();
                const [account, onboarding] = await Promise.all([fetchCurrentAccount(token), fetchOnboardingStatus(token)]);
                // Unlinked accounts can export or request deletion without creating a profile.
                const groups = onboarding.linked && onboarding.terms_accepted ? await fetchMyGroups(token) : [];
                if (active) setData({ account, groups, linked: onboarding.linked });
            } catch {
                if (active) setError("Could not load your account and groups. Please refresh to try again.");
            }
        })();
        return () => { active = false; };
    }, [getToken, isLoaded]);
    const exportData = async () => {
        setExporting(true);
        setError(null);
        try { await downloadMyData(await getToken()); }
        catch { setError("Could not download your data. Please try again."); }
        finally { setExporting(false); }
    };
    return <div className="min-h-screen bg-[#111820] text-slate-100">
        <AppHeader />
        <main className="mx-auto max-w-2xl space-y-5 px-4 py-8">
            <h1 className="font-serif text-3xl font-bold">Account / Data</h1>
            {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
            {!data && !error && <p role="status" className="text-slate-400">Loading account…</p>}
            {data && <AccountDataView {...data} exporting={exporting} onExport={() => void exportData()} />}
            {data?.linked && data.account.terms_accepted && <MembershipSettings getToken={getToken} checkoutReturn={checkoutReturn} />}
            {data?.linked && <SessionReminderSettings email={data.account.email} getToken={getToken} />}
            <PrivacySupportLinks />
        </main>
    </div>;
}
