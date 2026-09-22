import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import PrivacyPage from "../app/privacy/page";
import LandingPage from "../app/page";
import SupportPage from "../app/support/page";
import AccountDataView from "../components/AccountDataView";
import { AppHeader } from "../components/AppShell";
import { downloadMyData, type MyGroup } from "../services/api";
import { supportContactUrl } from "./supportContact";

vi.mock("@clerk/nextjs", () => ({
    UserButton: () => null,
    useAuth: () => ({ isLoaded: true, isSignedIn: false, getToken: vi.fn() }),
    Show: ({ when, children }: { when: string; children: ReactNode }) => when === "signed-out" ? children : null,
    SignInButton: ({ children }: { children: ReactNode }) => children,
    SignUpButton: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/components/InteractiveGroupDemo", () => ({ InteractiveGroupDemo: () => null }));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => null }));

afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe("privacy, support and account surfaces", () => {
    it("renders public information and discoverable privacy/support/account links", () => {
        const privacy = renderToStaticMarkup(createElement(PrivacyPage));
        expect(privacy).toContain("Clerk handles sign-in");
        expect(privacy).toContain("14 days");
        expect(privacy).toContain("90 days");
        expect(privacy).toContain("Deployment safety backups");
        const landing = renderToStaticMarkup(createElement(LandingPage));
        const footer = landing.slice(landing.indexOf("<footer"));
        expect(footer).toContain('href="/privacy"');
        expect(footer).toContain('href="/support"');
        expect(renderToStaticMarkup(createElement(AppHeader))).toContain('aria-label="Account / Data"');
    });

    it("reads the support contact at runtime and safely handles missing/unsafe values", () => {
        vi.stubEnv("SUPPORT_CONTACT_URL", "");
        expect(renderToStaticMarkup(createElement(SupportPage))).toContain("Support contact is not configured yet");
        vi.stubEnv("SUPPORT_CONTACT_URL", "javascript:alert(1)");
        expect(renderToStaticMarkup(createElement(SupportPage))).not.toContain("javascript:");
        vi.stubEnv("SUPPORT_CONTACT_URL", "https://example.test/help");
        expect(renderToStaticMarkup(createElement(SupportPage))).toContain('href="https://example.test/help"');
        expect(supportContactUrl("mailto:support@example.test")).toBe("mailto:support@example.test");
        for (const unsafe of ["http://example.test", "data:text/html,test", "//example.test", "https://user:pass@example.test", "mailto:a@example.test%0d%0aBcc:other@example.test"]) {
            expect(supportContactUrl(unsafe)).toBeNull();
        }
    });

    const account = { id: "account-id", display_name: "Test account", username: "test", email: "self@example.test" };
    const group: MyGroup = { id: "group-id", name: "Owned group", role: "owner", member_count: 2, timezone: "UTC" };

    it("shows export and blocks the request link until owned groups are resolved", () => {
        const html = renderToStaticMarkup(createElement(AccountDataView, { account, groups: [group], exporting: false, onExport: vi.fn() }));
        expect(html).toContain("Download my data");
        expect(html).toContain("transfer ownership or delete these groups");
        expect(html).toContain('href="/groups/group-id/settings"');
        expect(html).not.toContain('href="/support#account-deletion"');
    });

    it("provides the operator-assisted support path for members and unlinked accounts", () => {
        for (const groups of [[], [{ ...group, role: "member" as const }]]) {
            const html = renderToStaticMarkup(createElement(AccountDataView, { account, groups, exporting: false, onExport: vi.fn() }));
            expect(html).toContain('href="/support#account-deletion"');
            expect(html).toContain("does not immediately delete");
        }
    });

    it("downloads only from the authenticated export endpoint and releases the blob", async () => {
        vi.useFakeTimers();
        const click = vi.fn();
        const remove = vi.fn();
        const anchor = { href: "", download: "", click, remove };
        vi.stubGlobal("document", { createElement: () => anchor, body: { appendChild: vi.fn() } });
        const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
        const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
        const fetcher = vi.fn().mockResolvedValue(new Response("{}", { headers: { "Content-Type": "application/json" } }));
        vi.stubGlobal("fetch", fetcher);
        await downloadMyData("test-token");
        expect(fetcher).toHaveBeenCalledWith("/api/me/export", { headers: { Authorization: "Bearer test-token" }, cache: "no-store" });
        expect(createUrl).toHaveBeenCalledOnce();
        expect(anchor.download).toBe("dnd-planner-personal-data.json");
        expect(click).toHaveBeenCalledOnce();
        expect(remove).toHaveBeenCalledOnce();
        vi.runAllTimers();
        expect(revoke).toHaveBeenCalledWith("blob:test");
        fetcher.mockResolvedValue(new Response("Unauthorized", { status: 401 }));
        await expect(downloadMyData()).rejects.toThrow("Could not export");
        expect(click).toHaveBeenCalledOnce();
    });
});
