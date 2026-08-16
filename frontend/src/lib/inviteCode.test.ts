import { describe, expect, it } from "vitest";

import { formatInviteCodeInput } from "./inviteCode";

describe("invite code input", () => {
    it("normalizes lowercase codes and optional separators for the join form", () => {
        expect(formatInviteCodeInput("k7m4pq2x")).toBe("K7M4-PQ2X");
        expect(formatInviteCodeInput("k7m4-pq2x")).toBe("K7M4-PQ2X");
    });

    it("keeps the input short and human-readable", () => {
        expect(formatInviteCodeInput("k7m4-pq2x-extra")).toBe("K7M4-PQ2X");
    });
});
