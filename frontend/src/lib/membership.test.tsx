import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MembershipPanel } from "../components/MembershipSettings";
import { createGroup, fetchMembership, openBillingPortal, startMembershipCheckout, type Membership } from "../services/api";

vi.mock("@/components/AppShell", () => ({ SurfacePanel: "section" }));
afterEach(() => vi.unstubAllGlobals());

const free: Membership = { billing_enabled: true, plan: "free", owned_groups: 2, owned_group_limit: 2, subscription: null, can_manage_billing: false,
    free_owned_group_limit: 2, prices: { month: "€3.90", year: "€39" }, gift_url: "https://buy.stripe.com/test_gift" };
const pro: Membership = {
    ...free, plan: "pro", owned_group_limit: null, can_manage_billing: true,
    subscription: { status: "active", billing_interval: "year", current_period_end: "2027-10-17T00:00:00Z", cancel_at_period_end: false },
};
const panel = (membership: Membership, extra: Partial<Parameters<typeof MembershipPanel>[0]> = {}) => renderToStaticMarkup(createElement(MembershipPanel, {
    membership, busy: false, error: null, checkoutReturn: null, onCheckout: vi.fn(), onManage: vi.fn(), ...extra,
}));

describe("membership", () => {
    it("offers both upgrades on the free plan and shows the group allowance", () => {
        const html = panel(free);
        expect(html).toMatch(/>Free<\/h3><span[^>]*>Current plan/);
        expect(html).toContain("You own 2 of 2 groups");
        expect(html).toContain("Upgrade monthly");
        expect(html).toContain("Upgrade yearly");
        expect(html).not.toContain(">Manage billing</button>");
        expect(html).toContain("€3.90/month or €39/year");
        expect(html).toContain("Own up to 2 groups");
        expect(html).toContain('href="https://buy.stripe.com/test_gift"');
    });

    it("hides the gift card without a Payment Link and thanks gift givers", () => {
        expect(panel({ ...free, gift_url: null })).not.toContain("One-time gift");
        expect(panel(free, { checkoutReturn: "gift" })).toContain("Thank you so much for your gift!");
    });

    it("shows renewal, cancellation, failed payment and checkout return states for PRO", () => {
        const html = panel(pro, { checkoutReturn: "success" });
        expect(html).toMatch(/>PRO<\/h3><span[^>]*>Current plan/);
        expect(html).toContain("Renews on");
        expect(html).toContain("Manage billing");
        expect(html).toContain("Thanks! PRO is active.");
        expect(html).not.toContain("Upgrade monthly");
        expect(panel({ ...pro, subscription: { ...pro.subscription!, cancel_at_period_end: true } })).toContain("PRO ends on");
        expect(panel({ ...pro, subscription: { ...pro.subscription!, status: "past_due" } })).toContain("Your last payment failed");
        expect(panel(free, { checkoutReturn: "success" })).toContain("as soon as Stripe confirms");
        expect(panel(free, { checkoutReturn: "cancelled" })).toContain("Nothing was charged");
    });

    it("calls the authenticated membership endpoints and surfaces the group limit message", async () => {
        const fetcher = vi.fn()
            .mockResolvedValueOnce(new Response(JSON.stringify(free)))
            .mockResolvedValueOnce(new Response(JSON.stringify({ url: "https://checkout.stripe.test" })))
            .mockResolvedValueOnce(new Response(JSON.stringify({ url: "https://billing.stripe.test" })))
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Free accounts can own up to 2 groups." }), { status: 403 }));
        vi.stubGlobal("fetch", fetcher);
        expect(await fetchMembership("token")).toEqual(free);
        expect(await startMembershipCheckout("year", "token")).toBe("https://checkout.stripe.test");
        expect(fetcher).toHaveBeenCalledWith("/api/billing/checkout", expect.objectContaining({ method: "POST", body: JSON.stringify({ interval: "year" }) }));
        expect(await openBillingPortal("token")).toBe("https://billing.stripe.test");
        await expect(createGroup({ name: "Third" }, "token")).rejects.toThrow("Free accounts can own up to 2 groups.");
    });
});
