"use client";

import { useEffect, useState, type ReactNode } from "react";
import { SurfacePanel } from "@/components/AppShell";
import { fetchMembership, openBillingPortal, startMembershipCheckout, type BillingInterval, type Membership } from "@/services/api";

export type CheckoutReturn = "success" | "cancelled" | "gift" | null;

function renewalLine(subscription: NonNullable<Membership["subscription"]>): string | null {
    if (!subscription.current_period_end) return null;
    const date = new Date(subscription.current_period_end).toLocaleDateString();
    return subscription.cancel_at_period_end ? `PRO ends on ${date}.` : `Renews on ${date}.`;
}

const goldButton = "rounded-md bg-[#d5a75b] px-3 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50";
const outlineButton = "rounded-md border border-amber-200/50 px-3 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-200/10 disabled:opacity-50";

function PlanCard({ title, price, current, children }: { title: string; price: string; current: boolean; children: ReactNode }) {
    return <div className={`flex flex-col gap-3 rounded-lg border p-4 ${current ? "border-amber-200/70 bg-amber-200/[0.06]" : "border-slate-700 bg-[#141c26]/70"}`}>
        <div className="flex items-start justify-between gap-2">
            <h3 className="font-serif text-lg font-bold text-stone-100">{title}</h3>
            {current && <span className="rounded-full border border-amber-200/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-100">Current plan</span>}
        </div>
        <p className="text-sm font-semibold text-amber-100">{price}</p>
        {children}
    </div>;
}

export function MembershipPanel({ membership, busy, error, checkoutReturn, onCheckout, onManage }: {
    membership: Membership; busy: boolean; error: string | null; checkoutReturn: CheckoutReturn;
    onCheckout: (interval: BillingInterval) => void; onManage: () => void;
}) {
    const pro = membership.plan === "pro";
    const subscription = membership.subscription;
    const freeLimit = membership.free_owned_group_limit;
    return <SurfacePanel className="space-y-4 p-5">
        <div className="space-y-1">
            <h2 className="font-serif text-xl text-stone-100">Membership</h2>
            <p className="text-sm text-slate-400">DnD Planner is a passion project, made because my friends and I needed it. If it helps your table, you can support it with PRO or a one-time gift. Players never need to pay to join a group.</p>
        </div>
        {checkoutReturn === "success" && !pro && <p role="status" className="text-sm text-emerald-300">Thanks! PRO switches on as soon as Stripe confirms your payment. Refresh this page in a moment.</p>}
        {checkoutReturn === "success" && pro && <p role="status" className="text-sm text-emerald-300">Thanks! PRO is active.</p>}
        {checkoutReturn === "cancelled" && <p role="status" className="text-sm text-slate-400">Checkout was cancelled. Nothing was charged.</p>}
        {checkoutReturn === "gift" && <p role="status" className="text-sm text-emerald-300">Thank you so much for your gift!</p>}
        {pro && subscription?.status === "past_due" && <p className="text-sm text-amber-200">Your last payment failed. Update your payment method in Manage billing to keep PRO.</p>}
        <div className="grid gap-3 sm:grid-cols-3">
            <PlanCard title="Free" price="€0" current={!pro}>
                <ul className="space-y-1 text-sm text-slate-400">
                    <li>Own up to {freeLimit ?? "a few"} groups</li>
                    <li>Join as many groups as you like</li>
                </ul>
                {!pro && <p className="mt-auto text-xs text-slate-500">You own {membership.owned_groups} of {membership.owned_group_limit ?? "unlimited"} groups.</p>}
            </PlanCard>
            <PlanCard title="PRO" price={membership.prices ? `${membership.prices.month}/month or ${membership.prices.year}/year` : "Monthly or yearly"} current={pro}>
                <ul className="space-y-1 text-sm text-slate-400">
                    <li>Own unlimited groups</li>
                    <li>Supports the project</li>
                    <li>Cancel anytime</li>
                </ul>
                {pro && subscription && renewalLine(subscription) && <p className="text-xs text-slate-500">{renewalLine(subscription)}</p>}
                {!pro && <div className="mt-auto flex flex-wrap gap-2">
                    <button onClick={() => onCheckout("month")} disabled={busy} className={goldButton}>Upgrade monthly</button>
                    <button onClick={() => onCheckout("year")} disabled={busy} className={goldButton}>Upgrade yearly</button>
                </div>}
            </PlanCard>
            {membership.gift_url && <PlanCard title="One-time gift" price="Pay what you want" current={false}>
                <p className="text-sm text-slate-400">No subscription. Chip in once to say thanks and help cover hosting.</p>
                <a href={membership.gift_url} target="_blank" rel="noopener noreferrer" className={`mt-auto text-center ${goldButton}`}>Send a gift</a>
            </PlanCard>}
        </div>
        {membership.can_manage_billing && <button onClick={onManage} disabled={busy} className={outlineButton}>Manage billing</button>}
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
