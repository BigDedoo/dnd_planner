import { describe, expect, it } from "vitest";

import { bestDateReason, rankBestDates } from "./bestDates";

describe("best-date recommendations", () => {
    it("ranks available before maybe and uses date as a stable tie-breaker", () => {
        const rows = [
            ["2026-08-29", "Available"],
            ["2026-08-29", "Available"],
            ["2026-08-30", "Available"],
            ["2026-08-30", "Maybe"],
            ["2026-08-28", "Maybe"],
        ].map(([date, status], index) => ({
            group_name: "Group",
            user_name: `User ${index}`,
            date,
            status,
        }));
        const ranked = rankBestDates(rows, 3, "2026-08-28");
        expect(ranked.map((entry) => entry.day)).toEqual([
            "2026-08-29",
            "2026-08-30",
            "2026-08-28",
        ]);
        expect(bestDateReason(ranked[1], 3)).toBe("1 available, 1 maybe");
    });

    it("excludes past dates", () => {
        expect(
            rankBestDates(
                [{ group_name: "G", user_name: "U", date: "2026-08-01", status: "Available" }],
                1,
                "2026-08-02"
            )
        ).toEqual([]);
    });
});
