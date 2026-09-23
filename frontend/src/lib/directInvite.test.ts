import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { InviteJoinForm, InviteUnavailable } from "@/components/DirectInvitePanels";
import { directInvitePath, directInviteUrl, joinAndOpenInvitedGroup } from "./directInvite";
import { safeOnboardingNext } from "./onboarding";

describe("direct invite return paths", () => {
    it("preserves a normalized invite path through sign-in and onboarding", () => {
        const path = directInvitePath("k7m4pq2x");
        expect(path).toBe("/join/K7M4-PQ2X");
        expect(safeOnboardingNext(path)).toBe(path);
        expect(directInviteUrl("https://dnd-planner.example/", " k7m4 - pq2x ")).toBe("https://dnd-planner.example/join/K7M4-PQ2X");
    });

    it("rejects unsafe return paths", () => {
        expect(safeOnboardingNext("https://example.com")).toBe("/app");
        expect(safeOnboardingNext("//example.com")).toBe("/app");
        expect(safeOnboardingNext("/\\example.com")).toBe("/app");
        expect(safeOnboardingNext("/%2f%2fexample.com")).toBe("/app");
    });

    it("shows one non-enumerating unavailable-invite message", () => {
        const html = renderToStaticMarkup(createElement(InviteUnavailable, { message: "Invite code is invalid or has been revoked" }));
        expect(html).toContain("This invitation is no longer available.");
        expect(html).toContain("revoked or replaced");
        expect(html).toContain('href="/app"');
        expect(html).not.toContain("never existed");
        const unexpected = renderToStaticMarkup(createElement(InviteUnavailable, { message: "internal infrastructure detail" }));
        expect(unexpected).toContain("Could not check this invitation.");
        expect(unexpected).not.toContain("internal infrastructure detail");
    });

    it("keeps the nickname and API error visible while join is pending or fails", () => {
        const html = renderToStaticMarkup(createElement(InviteJoinForm, {
            groupName: "A long campaign name", nickname: "Lyra", joining: true,
            error: "Group mutations are temporarily disabled",
            onNicknameChange: vi.fn(), onSubmit: vi.fn(),
        }));
        expect(html).toContain("A long campaign name");
        expect(html).toContain('value="Lyra"');
        expect(html).toContain("Joining group...");
        expect(html).toContain('disabled=""');
        expect(html).toContain("Group mutations are temporarily disabled");
    });

    it("redirects after a successful join or an already-member result, but not on failure", async () => {
        const getToken = vi.fn().mockResolvedValue("token");
        const join = vi.fn().mockResolvedValueOnce({ id: "group-id", joined: true }).mockResolvedValueOnce({ id: "group-id", joined: false });
        const replace = vi.fn();
        await joinAndOpenInvitedGroup("K7M4-PQ2X", "Lyra", getToken, join, replace);
        await joinAndOpenInvitedGroup("K7M4-PQ2X", undefined, getToken, join, replace);
        expect(join).toHaveBeenNthCalledWith(1, "K7M4-PQ2X", "Lyra", "token");
        expect(replace).toHaveBeenCalledTimes(2);
        expect(replace).toHaveBeenLastCalledWith("/groups/group-id");
        join.mockRejectedValueOnce(new Error("Group mutations are temporarily disabled"));
        await expect(joinAndOpenInvitedGroup("K7M4-PQ2X", "Lyra", getToken, join, replace)).rejects.toThrow("temporarily disabled");
        expect(replace).toHaveBeenCalledTimes(2);
    });
});
