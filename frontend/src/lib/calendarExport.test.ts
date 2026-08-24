import { describe, expect, it } from "vitest";

import { googleCalendarUrl } from "./calendarExport";

describe("calendar exports", () => {
    it("builds a Google Calendar template without an external redirect target", () => {
        const url = new URL(googleCalendarUrl({
            id: "session",
            group_id: "group",
            day: "2026-08-29",
            confirmed_by_user_id: "owner",
            confirmed_at: "2026-08-01T00:00:00Z",
            title: "Dragon hunt",
            start_time: "19:00:00",
            duration_minutes: 180,
        }, "Green Flag"));
        expect(url.origin).toBe("https://calendar.google.com");
        expect(url.searchParams.get("text")).toBe("Dragon hunt");
        expect(url.searchParams.get("dates")).toContain("T190000/");
    });
});
