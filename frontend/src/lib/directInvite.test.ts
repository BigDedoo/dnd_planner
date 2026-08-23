import { describe, expect, it } from "vitest";

import { directInvitePath } from "./directInvite";
import { safeOnboardingNext } from "./onboarding";

describe("direct invite return paths", () => {
    it("preserves a normalized invite path through sign-in and onboarding", () => {
        const path = directInvitePath("k7m4pq2x");
        expect(path).toBe("/join/K7M4-PQ2X");
        expect(safeOnboardingNext(path)).toBe(path);
    });

    it("rejects unsafe return paths", () => {
        expect(safeOnboardingNext("https://example.com")).toBe("/app");
        expect(safeOnboardingNext("//example.com")).toBe("/app");
        expect(safeOnboardingNext("/\\example.com")).toBe("/app");
        expect(safeOnboardingNext("/%2f%2fexample.com")).toBe("/app");
    });
});
