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
});
