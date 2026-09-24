import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AvailabilityModeControl } from "@/components/AvailabilityModeControl";
import { updateOwnAvailabilityMode } from "@/services/api";
import { availabilityModeChoices, availabilitySaveFeedback, confirmedAvailabilityModeChange } from "./availabilityMode";

afterEach(() => vi.unstubAllGlobals());

describe("group availability mode UX", () => {
    const render = (mode: "global" | "separate", error: string | null = null, updating = false) =>
        renderToStaticMarkup(createElement(AvailabilityModeControl, {
            mode, updating, error, notice: null, onSwitch: vi.fn(),
        }));

    it("renders a compact Global selector and accessible help without a standalone card", () => {
        const html = render("global");
        expect(html).toContain("Availability");
        expect(html).toContain("🌐 Global");
        expect(html).toContain('aria-label="Availability mode"');
        expect(html).toContain("Global: your availability is shared across groups.");
        expect(html).not.toContain("Manage separately for this group");
        expect(html).not.toContain("rounded-md border border-slate-700/80");
    });

    it("renders This group mode and both dropdown choices", () => {
        const html = render("separate");
        expect(html).toContain("👥 This group");
        expect(availabilityModeChoices).toEqual([
            { value: "global", label: "🌐 Global" },
            { value: "separate", label: "👥 This group only" },
        ]);
        expect(html).not.toContain("Separate for this group");
    });

    it("confirms only the first switch, cancels without mutation, and preserves API errors", async () => {
        const update = vi.fn().mockResolvedValue("separate");
        const cancel = vi.fn().mockReturnValue(false);
        expect(await confirmedAvailabilityModeChange("separate", "Underdark", false, cancel, update)).toBeNull();
        expect(update).not.toHaveBeenCalled();
        expect(cancel.mock.calls[0][0]).toContain("Your current Global availability will be copied to this group.");
        expect(await confirmedAvailabilityModeChange("separate", "Underdark", false, () => true, update)).toBe("separate");
        expect(update).toHaveBeenCalledOnce();
        const shouldNotConfirm = vi.fn();
        expect(await confirmedAvailabilityModeChange("global", "Underdark", true, shouldNotConfirm, vi.fn().mockResolvedValue("global"))).toBe("global");
        expect(await confirmedAvailabilityModeChange("separate", "Underdark", true, shouldNotConfirm, update)).toBe("separate");
        expect(shouldNotConfirm).not.toHaveBeenCalled();
        const failure = vi.fn().mockRejectedValue(new Error("temporarily disabled"));
        await expect(confirmedAvailabilityModeChange("global", "Underdark", true, shouldNotConfirm, failure)).rejects.toThrow("temporarily disabled");
        expect(render("separate", "temporarily disabled")).toContain('role="alert"');
    });

    it("disables switching while an availability change is in progress", () => {
        expect(render("global", null, true)).toContain("disabled");
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
