import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import TermsAcceptanceControl from "@/components/TermsAcceptanceControl";
import LegalLinks from "@/components/LegalLinks";
import TermsPage from "@/app/terms/page";
import LegalPage from "@/app/legal/page";
import CookiesPage from "@/app/cookies/page";
import PrivacyPage from "@/app/privacy/page";
import SupportPage from "@/app/support/page";
import { acceptTerms, fetchMyGroups } from "@/services/api";
import { canEnterPlanner, safeOnboardingNext } from "./onboarding";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("legal content and explicit agreement", () => {
    it("uses the supported Clerk opt-out in the root provider and Next server/client configuration", () => {
        const layout = readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");
        const config = readFileSync(new URL("../../next.config.ts", import.meta.url), "utf8");
        expect(layout).toContain("<ClerkProvider telemetry={false}>");
        expect(config).toContain('NEXT_PUBLIC_CLERK_TELEMETRY_DISABLED: "1"');
    });
    it("requires an unchecked Terms-only checkbox with separate informational Privacy link", () => {
        const html = renderToStaticMarkup(createElement(TermsAcceptanceControl, { checked: false, onChange: vi.fn(), version: "review" }));
        expect(html).toContain('type="checkbox"');
        expect(html).toContain('required=""');
        expect(html).not.toContain('checked=""');
        expect(html).toContain('href="/terms"');
        expect(html).toContain('href="/privacy"');
        expect(html.match(/type="checkbox"/g)).toHaveLength(1);
        expect(html).not.toContain("agree to the Privacy");
        expect(html).toContain("See how DnD Planner handles your data");
    });

    it("handles both first onboarding and existing accounts requiring renewed agreement", () => {
        for (const status of [{ linked: false, terms_accepted: false }, { linked: false, terms_accepted: true }, { linked: true, terms_accepted: false }]) expect(canEnterPlanner(status)).toBe(false);
        expect(canEnterPlanner({ linked: true, terms_accepted: true })).toBe(true);
        expect(safeOnboardingNext("/join/K7M4-PQ2X")).toBe("/join/K7M4-PQ2X");
        for (const next of ["//outside.test", "https://outside.test", "/onboarding?next=/onboarding", "/%2fonboarding", "/\\outside.test"]) expect(safeOnboardingNext(next)).toBe("/app");
        const source = readFileSync(new URL("../app/onboarding/page.tsx", import.meta.url), "utf8");
        expect(source).toContain("if (!status.linked) await completeOnboarding");
        expect(source).toContain("if (!status.terms_accepted) await acceptTerms");
        expect(source).toContain("useState(false)");
    });

    it("sends only the selected server version and reports a stale version", async () => {
        const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ terms_accepted: true })));
        vi.stubGlobal("fetch", fetcher);
        await acceptTerms("current-version", "token");
        expect(fetcher).toHaveBeenCalledWith("/api/me/terms", expect.objectContaining({ method: "PUT", body: JSON.stringify({ terms_version: "current-version" }), headers: expect.objectContaining({ Authorization: "Bearer token" }) }));
        fetcher.mockResolvedValue(new Response("{}", { status: 409 }));
        await expect(acceptTerms("stale", "token")).rejects.toThrow("Terms have changed");
    });

    it("redirects stale planner tabs on the machine-readable backend gate", async () => {
        const dispatchEvent = vi.fn();
        vi.stubGlobal("window", { dispatchEvent });
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: "terms_acceptance_required" } }), { status: 403 })));
        await expect(fetchMyGroups("token")).rejects.toThrow("Terms of Use");
        expect(dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "dnd-planner:terms-required" }));
    });

    it("renders all legal links, reporting categories and truthful missing-identity placeholders", () => {
        vi.stubEnv("LEGAL_OPERATOR_NAME", "");
        vi.stubEnv("SUPPORT_CONTACT_URL", "");
        const nav = renderToStaticMarkup(createElement(LegalLinks));
        for (const path of ["terms", "privacy", "legal", "cookies", "support"]) expect(nav).toContain(`href="/${path}"`);
        const legal = renderToStaticMarkup(createElement(LegalPage));
        expect(legal).toContain("Publisher details require confirmation");
        expect(legal).toContain("OVH SAS");
        expect(legal).toContain("RCS Lille Métropole 424 761 419 00045");
        const support = renderToStaticMarkup(createElement(SupportPage));
        for (const category of ["technical-help", "privacy-rights", "account-deletion", "report-content"]) expect(support).toContain(`id="${category}"`);
        expect(support).toContain("Support contact is not configured yet");
    });

    it("has no age policy, paid terms, marketing opt-in or cookie banner", () => {
        const html = [TermsPage, LegalPage, CookiesPage, PrivacyPage, SupportPage].map(Page => renderToStaticMarkup(createElement(Page))).join(" ");
        expect(html).not.toMatch(/\b(age|parental|minor|children|18\+|16\+|subscription|payment|refund|purchase|billing)\b/i);
        expect(html).not.toMatch(/role="dialog"|accept all cookies|reject all cookies|marketing opt-in/i);
        expect(html).toContain("Wizards of the Coast");
        expect(html).toContain("14 days");
        expect(html).toContain("90 days");
        expect(html).toContain("not cookie-free");
    });
});
