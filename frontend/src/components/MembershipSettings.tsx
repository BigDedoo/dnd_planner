"use client";

import { useEffect, useState } from "react";
import { SurfacePanel } from "@/components/AppShell";
import { fetchMembership, openBillingPortal, startMembershipCheckout, type BillingInterval, type Membership } from "@/services/api";

export type CheckoutReturn = "success" | "cancelled" | null;

function renewalLine(subscription: NonNullable<Membership["subscription"]>): string | null {
    if (!subscription.current_period_end) return null;
    const date = new Date(subscription.current_period_end).toLocaleDateString();
    return subscription.cancel_at_period_end ? `PRO ends on ${date}.` : `Renews on ${date}.`;
}

export function MembershipPanel({ membership, busy, error, checkoutReturn, onCheckout, onManage }: {
    membership: Membership; busy: boolean; error: string | null; checkoutReturn: CheckoutReturn;
    onCheckout: (interval: BillingInterval) => void; onManage: () => void;
}) {
    const pro = membership.plan === "pro";
    const subscription = membership.subscription;
    return <SurfacePanel className="space-y-3 p-5">
        <h2 className="font-serif text-xl text-stone-100">Membership</h2>
        {checkoutReturn === "success" && !pro && <p role="status" className="text-sm text-emerald-300">Thanks! PRO switches on as soon as Stripe confirms your payment. Refresh this page in a moment.</p>}
        {checkoutReturn === "success" && pro && <p role="status" className="text-sm text-emerald-300">Thanks! PRO is active.</p>}
        {checkoutReturn === "cancelled" && <p role="status" className="text-sm text-slate-400">Checkout was cancelled. Nothing was charged.</p>}
        <p className="text-sm text-slate-300">Current plan: <span className="font-semibold text-stone-100">{pro ? "PRO" : "Free"}</span></p>
        {pro && subscription?.status === "past_due" && <p className="text-sm text-amber-200">Your last payment failed. Update your payment method in Manage billing to keep PRO.</p>}
        {pro && subscription && renewalLine(subscription) && <p className="text-sm text-slate-400">{renewalLine(subscription)}</p>}
        {!pro && <>
            <p className="text-sm text-slate-400">You own {membership.owned_groups} of {membership.owned_group_limit ?? "unlimited"} groups on the free plan. Players never need to pay to join a group.</p>
            <p className="text-sm text-slate-400">DnD Planner is a passion project, made because my friends and I needed it. If it helps your table, PRO is a way to support it: you can own unlimited groups, and you can cancel anytime from Manage billing.</p>
            <div className="flex flex-wrap gap-2">
                <button onClick={() => onCheckout("month")} disabled={busy} className="rounded-md bg-[#d5a75b] px-4 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50">Upgrade monthly</button>
                <button onClick={() => onCheckout("year")} disabled={busy} className="rounded-md bg-[#d5a75b] px-4 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50">Upgrade yearly</button>
            </div>
        </>}
        {membership.can_manage_billing && <button onClick={onManage} disabled={busy} className="rounded-md border border-amber-200/50 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-200/10 disabled:opacity-50">Manage billing</button>}
        {busy && <p role="status" className="text-sm text-slate-400">Opening Stripe…</p>}
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    </SurfacePanel>;
}

export default function MembershipSettings({ getToken, checkoutReturn }: { getToken: () => Promise<string | null>; checkoutReturn: CheckoutReturn }) {
    const [membership, setMembership] = useState<Membership | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        let active = true;
        void (async () => {
            try {
                const result = await fetchMembership(await getToken());
                if (active) setMembership(result);
            } catch (failure) {
                if (active) setError(failure instanceof Error ? failure.message : "Could not load your membership.");
            }
        })();
        return () => { active = false; };
    }, [getToken]);
    const redirect = async (open: (token: string | null) => Promise<string>) => {
        setBusy(true); setError(null);
        try {
            window.location.assign(await open(await getToken()));
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : "Could not reach billing. Please try again.");
            setBusy(false);
        }
    };
    if (!membership) return error ? <p role="alert" className="text-sm text-rose-300">{error}</p> : null;
    // Billing stays hidden until the operator switches it on.
    if (!membership.billing_enabled) return null;
    return <MembershipPanel membership={membership} busy={busy} error={error} checkoutReturn={checkoutReturn}
        onCheckout={interval => void redirect(token => startMembershipCheckout(interval, token))}
        onManage={() => void redirect(openBillingPortal)} />;
}
