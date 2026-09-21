import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { safeOnboardingNext } from "./onboarding";

describe("onboarding redirect", () => {
    it("keeps an internal next path", () => {
        expect(safeOnboardingNext("/groups/group-123")).toBe("/groups/group-123");
    });

    it("rejects external redirect targets", () => {
        expect(safeOnboardingNext("//example.com")).toBe("/app");
        expect(safeOnboardingNext("https://example.com")).toBe("/app");
    });

    it("keeps onboarding and the API client free of retired recovery access", () => {
        const onboardingSource = readFileSync(
            new URL("../app/onboarding/page.tsx", import.meta.url),
            "utf8"
        );
        const apiSource = readFileSync(
            new URL("../services/api.ts", import.meta.url),
            "utf8"
        );

        expect(onboardingSource).toContain("completeOnboarding");
        expect(onboardingSource).not.toMatch(/LegacyRecovery|recovery-profiles|Recover existing profile/);
        expect(apiSource).not.toMatch(/LegacyRecovery|recovery-profiles|onboarding\/recover/);
    });
});
