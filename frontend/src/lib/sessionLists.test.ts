import { describe, expect, it } from "vitest";

import { splitGroupSessions } from "./sessionLists";

const base = {
    group_id: "group",
    confirmed_by_user_id: "owner",
    confirmed_at: "2026-08-01T00:00:00Z",
};

describe("group session lists", () => {
    it("separates upcoming, past, and cancelled sessions", () => {
        const result = splitGroupSessions([
            { ...base, id: "future", day: "2026-08-30" },
            { ...base, id: "past", day: "2026-08-01" },
            { ...base, id: "cancelled", day: "2026-08-29", cancelled_at: "2026-08-20T00:00:00Z" },
        ], "2026-08-23");
        expect(result.upcoming.map((session) => session.id)).toEqual(["future"]);
        expect(result.past.map((session) => session.id)).toEqual(["past"]);
        expect(result.cancelled.map((session) => session.id)).toEqual(["cancelled"]);
    });
});
