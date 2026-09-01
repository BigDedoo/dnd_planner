import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
    LegacyRecoveryChoice,
    LegacyRecoveryConfirmation,
    LegacyRecoveryProfileList,
} from "../components/LegacyProfileRecoveryOptions";
import {
    LegacyRecoveryConflictError,
    type LegacyRecoveryProfile,
} from "../services/api";
import {
    claimOrRefreshOnConflict,
    initialRecoveryMode,
    recoveryGroupSummary,
} from "./legacyProfileRecovery";

const profiles: LegacyRecoveryProfile[] = [
    {
        user_id: "00000000-0000-4000-8000-000000000001",
        display_name: "Daerrus",
        group_names: ["Green Flag", "1D6"],
    },
];

describe("legacy profile recovery onboarding", () => {
    it("keeps normal create onboarding when recovery is disabled or empty", () => {
        expect(initialRecoveryMode([])).toBe("create");
        expect(initialRecoveryMode(profiles)).toBe("choice");
    });

    it("renders deterministic group-name disambiguation data", () => {
        expect(recoveryGroupSummary(profiles[0])).toBe("Green Flag · 1D6");
        expect(recoveryGroupSummary({ ...profiles[0], group_names: [] })).toBe(
            "No groups listed"
        );
    });

    it("renders both recovery and normal new-profile onboarding paths", () => {
        const markup = renderToStaticMarkup(
            createElement(LegacyRecoveryChoice, {
                onCreate: vi.fn(),
                onRecover: vi.fn(),
            })
        );
        expect(markup).toContain("Recover existing profile");
        expect(markup).toContain("Create a new profile");
    });

    it("renders the safe recovery list with names and group disambiguation", () => {
        const markup = renderToStaticMarkup(
            createElement(LegacyRecoveryProfileList, {
                profiles,
                onBack: vi.fn(),
                onCreate: vi.fn(),
                onSelect: vi.fn(),
            })
        );
        expect(markup).toContain("Daerrus");
        expect(markup).toContain("Green Flag · 1D6");
        expect(markup).not.toContain("email");
    });

    it("renders a lightweight confirmation before claiming", () => {
        const markup = renderToStaticMarkup(
            createElement(LegacyRecoveryConfirmation, {
                isSubmitting: false,
                profile: profiles[0],
                onCancel: vi.fn(),
                onConfirm: vi.fn(),
            })
        );
        expect(markup).toContain("Recover “Daerrus”?");
        expect(markup).toContain("Cancel");
        expect(markup).toContain("Recover profile");
    });

    it("returns a successful claim for the existing safe redirect flow", async () => {
        const result = await claimOrRefreshOnConflict(
            profiles[0].user_id,
            vi.fn().mockResolvedValue({
                linked: true,
                suggested_display_name: null,
                user_id: profiles[0].user_id,
            }),
            vi.fn(),
        );
        expect(result.status).toBe("claimed");
        expect(result.status === "claimed" && result.onboarding.linked).toBe(true);
    });

    it("refreshes the available list after a concurrent conflict", async () => {
        const refresh = vi.fn().mockResolvedValue([]);
        const result = await claimOrRefreshOnConflict(
            profiles[0].user_id,
            vi.fn().mockRejectedValue(
                new LegacyRecoveryConflictError("This profile is no longer available")
            ),
            refresh,
        );
        expect(result).toEqual({ status: "conflict", profiles: [] });
        expect(refresh).toHaveBeenCalledOnce();
    });
});
