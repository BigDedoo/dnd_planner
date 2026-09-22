import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConfirmedSession } from "@/services/api";
import { googleCalendarUrl } from "./calendarExport";

const session: ConfirmedSession = {
    id: "session", group_id: "group", day: "2026-08-29",
    confirmed_by_user_id: "owner", confirmed_at: "2026-08-01T00:00:00Z",
    title: "Dragon hunt", notes: "Bring dice & snacks",
    start_time: "20:00:00", duration_minutes: 180, group_timezone: "Europe/Paris",
    starts_at_utc: "2026-08-29T18:00:00+00:00", ends_at_utc: "2026-08-29T21:00:00+00:00",
};

afterEach(() => vi.unstubAllEnvs());

describe("calendar exports", () => {
    it.each(["UTC", "Europe/Paris", "America/New_York", "Asia/Tokyo"])("exports exact UTC instants when the local timezone is %s", (zone) => {
        vi.stubEnv("TZ", zone);
        const url = new URL(googleCalendarUrl(session, "Green Flag"));
        expect(url.origin).toBe("https://calendar.google.com");
        expect(url.pathname).toBe("/calendar/render");
        expect(url.searchParams.get("action")).toBe("TEMPLATE");
        expect(url.searchParams.get("text")).toBe("Dragon hunt");
        expect(url.searchParams.get("details")).toBe("Bring dice & snacks");
        expect(url.searchParams.get("dates")).toBe("20260829T180000Z/20260829T210000Z");
    });

    it.each(["UTC", "Europe/Paris", "America/New_York", "Asia/Tokyo"])("keeps all-day events date-only in %s across DST and year-end", (zone) => {
        vi.stubEnv("TZ", zone);
        for (const [day, expected] of [["2026-03-29", "20260329/20260330"], ["2026-12-31", "20261231/20270101"]]) {
            const url = new URL(googleCalendarUrl({ ...session, day, title: null, start_time: null, duration_minutes: null, starts_at_utc: null, ends_at_utc: null }, "Green Flag"));
            expect(url.searchParams.get("dates")).toBe(expected);
            expect(url.searchParams.get("text")).toBe("Session — Green Flag");
        }
    });

    it("never silently falls back to browser-local time if UTC fields are missing", () => {
        expect(() => googleCalendarUrl({ ...session, starts_at_utc: undefined }, "Group")).toThrow("server UTC instants");
        expect(() => googleCalendarUrl({ ...session, starts_at_utc: "2026-08-29T20:00:00" }, "Group")).toThrow("server UTC instants");
    });
});
