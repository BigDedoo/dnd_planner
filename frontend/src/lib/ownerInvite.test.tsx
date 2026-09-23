import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OwnerInviteCardView } from "@/components/OwnerInviteCard";
import { generateGroupInvite, revokeGroupInvite } from "@/services/api";
import { directInviteUrl } from "./directInvite";
import { confirmedInviteMutation, copyInviteText, inviteCreatedLabel, inviteUseCountLabel, shareInviteLink } from "./invitePresentation";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: vi.fn() }) }));

const callbacks = {
    onGenerate: vi.fn(), onRevoke: vi.fn(), onCopyLink: vi.fn(), onCopyCode: vi.fn(),
    onShare: vi.fn(), onRetry: vi.fn(),
};
const inactive = { active: false, created_at: null, use_count: null };
const active = { active: true, created_at: "2026-09-23T12:00:00Z", use_count: 4 };
const base: ComponentProps<typeof OwnerInviteCardView> = { ...callbacks, status: inactive, code: null, url: null, loading: false, updating: false, canShare: false, error: null, notice: null };
const render = (overrides: Partial<typeof base> = {}) => renderToStaticMarkup(createElement(OwnerInviteCardView, { ...base, ...overrides }));

afterEach(() => vi.unstubAllGlobals());

describe("owner invite presentation", () => {
    it("shows creation only when no invite is active", () => {
        const html = render();
        expect(html).toContain("Create invite link");
        expect(html).not.toContain("Revoke invite");
        expect(html).not.toContain("Invite code");
    });

    it("shows the new code, primary copy link, status, joins, date and optional share", () => {
        const html = render({ status: active, code: "K7M4-PQ2X", url: directInviteUrl("https://example.test", "K7M4-PQ2X"), canShare: true });
        expect(html).toContain('value="K7M4-PQ2X"');
        expect(html).toContain("https://example.test/join/K7M4-PQ2X");
        for (const label of ["Active", "Copy link", "Copy code", "Share", "Replace invite", "Revoke invite", "Used 4 times", "Created Sep 23"]) expect(html).toContain(label);
        expect(render({ status: { ...active, use_count: 0 }, code: "K7M4-PQ2X", url: "https://example.test/join/K7M4-PQ2X" })).not.toContain(">Share</button>");
    });

    it("explains an active but unrecoverable code without inventing one", () => {
        const html = render({ status: active });
        expect(html).toContain("Active");
        expect(html).toContain("not stored in a recoverable form");
        expect(html).toContain("Replace invite");
        expect(html).not.toContain("Copy link");
        expect(html).not.toContain("value=");
    });

    it("provides live copy feedback, manual-copy fallback and a status-load retry", () => {
        expect(render({ status: active, code: "K7M4-PQ2X", url: "https://example.test/join/K7M4-PQ2X", notice: "Link copied" })).toContain('role="status"');
        const failed = render({ status: active, code: "K7M4-PQ2X", url: "https://example.test/join/K7M4-PQ2X", error: "Select the invite link above and copy it manually." });
        expect(failed).toContain('role="alert"');
        expect(failed).toContain('aria-label="Invite link to copy manually"');
        expect(render({ status: null, error: "Could not load invite status." })).toContain("Retry status");
    });

    it("formats successful-use counts and dates without calling them current members", () => {
        expect(inviteUseCountLabel(0)).toBe("No one has joined with this invite yet.");
        expect(inviteUseCountLabel(1)).toBe("Used 1 time");
        expect(inviteUseCountLabel(4)).toBe("Used 4 times");
        expect(inviteCreatedLabel("2026-09-23T12:00:00Z")).toBe("Created Sep 23");
    });

    it("requires confirmation before replacement or revocation, then uses the newly generated code", async () => {
        const operation = vi.fn().mockResolvedValueOnce({ code: "ABCD-EFGH" }).mockResolvedValueOnce(true);
        const cancel = vi.fn().mockReturnValue(false);
        expect(await confirmedInviteMutation("replace", cancel, operation)).toBeNull();
        expect(await confirmedInviteMutation("revoke", cancel, operation)).toBeNull();
        expect(operation).not.toHaveBeenCalled();
        expect(cancel.mock.calls[0][0]).toContain("invalidate the current invite link");
        expect(cancel.mock.calls[1][0]).toContain("no longer be able to join");
        const accept = vi.fn().mockReturnValue(true);
        const next = await confirmedInviteMutation<{ code: string }>("replace", accept, operation);
        expect(next).toEqual({ code: "ABCD-EFGH" });
        expect(render({ status: active, code: next?.code ?? null, url: "https://example.test/join/ABCD-EFGH" })).toContain('value="ABCD-EFGH"');
        expect(await confirmedInviteMutation("revoke", accept, operation)).toBe(true);
        expect(operation).toHaveBeenCalledTimes(2);
    });

    it("copies the exact link or code and exposes clipboard failures", async () => {
        const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
        await copyInviteText("https://example.test/join/K7M4-PQ2X", clipboard);
        await copyInviteText("K7M4-PQ2X", clipboard);
        expect(clipboard.writeText).toHaveBeenNthCalledWith(1, "https://example.test/join/K7M4-PQ2X");
        expect(clipboard.writeText).toHaveBeenNthCalledWith(2, "K7M4-PQ2X");
        await expect(copyInviteText("link", undefined)).rejects.toThrow("Clipboard is unavailable");
        clipboard.writeText.mockRejectedValueOnce(new Error("denied"));
        await expect(copyInviteText("link", clipboard)).rejects.toThrow("denied");
    });

    it("shares only the generated link and ignores native cancellation", async () => {
        const share = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce({ name: "AbortError" }).mockRejectedValueOnce(new Error("sharing failed"));
        expect(await shareInviteLink("https://example.test/join/K7M4-PQ2X", "Green flag", share)).toBe("shared");
        expect(share).toHaveBeenCalledWith({ title: "Join Green flag on DnD Planner", text: "Join our DnD group on DnD Planner.", url: "https://example.test/join/K7M4-PQ2X" });
        expect(await shareInviteLink("https://example.test/join/K7M4-PQ2X", "Green flag", share)).toBe("cancelled");
        await expect(shareInviteLink("https://example.test/join/K7M4-PQ2X", "Green flag", share)).rejects.toThrow("sharing failed");
    });

    it("surfaces disabled-mutation errors from the existing API", async () => {
        const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: "Invite mutations are temporarily disabled" }), { status: 503 })));
        vi.stubGlobal("fetch", fetcher);
        await expect(generateGroupInvite("group-id", "token")).rejects.toThrow("Invite mutations are temporarily disabled");
        await expect(revokeGroupInvite("group-id", "token")).rejects.toThrow("Invite mutations are temporarily disabled");
        expect(fetcher.mock.calls.map((call) => call[1].method)).toEqual(["POST", "DELETE"]);
    });
});
