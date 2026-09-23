import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AvailabilityModeControl } from "@/components/AvailabilityModeControl";
import { updateOwnAvailabilityMode } from "@/services/api";
import { availabilitySaveFeedback, confirmedAvailabilityModeChange } from "./availabilityMode";

afterEach(() => vi.unstubAllGlobals());

describe("group availability mode UX", () => {
    const render = (mode: "global" | "separate", error: string | null = null) =>
        renderToStaticMarkup(createElement(AvailabilityModeControl, {
            mode, groupName: "Underdark", updating: false, error, notice: null, onSwitch: vi.fn(),
        }));

    it("explains Global and offers Separate to every member", () => {
        expect(render("global")).toContain("Global availability");
        expect(render("global")).toContain("shared with every group");
        expect(render("global")).toContain("Manage separately for this group");
    });

    it("explains Separate without calling it a per-date fallback", () => {
        expect(render("separate")).toContain("Separate for this group");
        expect(render("separate")).toContain("only Underdark");
        expect(render("separate")).toContain("Use global availability");
    });

    it("cancels without mutation and returns the new mode only after API success", async () => {
        const update = vi.fn().mockResolvedValue("separate");
        const cancel = vi.fn().mockReturnValue(false);
        expect(await confirmedAvailabilityModeChange("separate", "Underdark", cancel, update)).toBeNull();
        expect(update).not.toHaveBeenCalled();
        expect(cancel.mock.calls[0][0]).toContain("copied as a starting point the first time");
        expect(await confirmedAvailabilityModeChange("separate", "Underdark", () => true, update)).toBe("separate");
        expect(update).toHaveBeenCalledOnce();
        const failure = vi.fn().mockRejectedValue(new Error("temporarily disabled"));
        await expect(confirmedAvailabilityModeChange("global", "Underdark", () => true, failure)).rejects.toThrow("temporarily disabled");
        expect(render("separate", "temporarily disabled")).toContain('role="alert"');
    });

    it("uses scope-aware transient save feedback", () => {
        expect(availabilitySaveFeedback("October 12", "global", "Underdark")).toContain("shared with your Global groups");
        expect(availabilitySaveFeedback("October 12", "separate", "Underdark")).toContain("Underdark only");
    });

    it("uses the authenticated personal mode endpoint and preserves mutation errors", async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ availability_mode: "separate" }), { status: 200 }))
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Availability mutations are temporarily disabled" }), { status: 503 }));
        vi.stubGlobal("fetch", fetcher);
        expect(await updateOwnAvailabilityMode("group-id", "separate", "token")).toEqual({ availability_mode: "separate" });
        expect(fetcher.mock.calls[0][0]).toBe("/api/groups/group-id/me/availability-mode");
        expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ availability_mode: "separate" });
        await expect(updateOwnAvailabilityMode("group-id", "global", "token")).rejects.toThrow("temporarily disabled");
    });
});
