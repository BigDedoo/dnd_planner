import { describe, expect, it } from "vitest";

import {
    availabilityForConfirmedSession,
    availabilityLabel,
    isConfirmedSessionMismatch,
    nextUpcomingConfirmedSession,
    sessionsForScheduleDay,
    upcomingConfirmedSessions,
} from "./mySchedule";

const sessions = [
    {
        id: "past",
        group_id: "group-past",
        group_name: "Past group",
        day: "2026-08-15",
        confirmed_by_user_id: "owner",
        confirmed_at: "2026-08-01T12:00:00Z",
        start_time: "20:00:00",
        my_rsvp: "going" as const,
    },
    {
        id: "underdark",
        group_id: "group-underdark",
        group_name: "Underdark",
        day: "2026-08-22",
        confirmed_by_user_id: "owner",
        confirmed_at: "2026-08-01T12:00:00Z",
        start_time: "18:00:00",
        my_rsvp: "maybe" as const,
    },
    {
        id: "green-flag",
        group_id: "group-green-flag",
        group_name: "Green flag",
        day: "2026-08-22",
        confirmed_by_user_id: "owner",
        confirmed_at: "2026-08-01T12:00:00Z",
    },
    {
        id: "avernus",
        group_id: "group-avernus",
        group_name: "Avernus",
        day: "2026-08-28",
        confirmed_by_user_id: "owner",
        confirmed_at: "2026-08-01T12:00:00Z",
    },
];

describe("My Schedule helpers", () => {
    it("sorts upcoming sessions and excludes past sessions", () => {
        expect(upcomingConfirmedSessions(sessions, "2026-08-20").map((session) => session.id)).toEqual([
            "underdark",
            "green-flag",
            "avernus",
        ]);
        expect(nextUpcomingConfirmedSession(sessions, "2026-08-20")?.id).toBe("underdark");
        expect(nextUpcomingConfirmedSession(sessions, "2026-09-01")).toBeNull();
    });

    it("keeps multiple groups visible for one calendar day", () => {
        expect(sessionsForScheduleDay(sessions, "2026-08-22").map((session) => session.group_name)).toEqual([
            "Underdark",
            "Green flag",
        ]);
        expect(sessionsForScheduleDay(sessions, "2026-08-15")).toEqual([sessions[0]]);
    });

    it("shows availability and flags an unavailable confirmed session", () => {
        const status = availabilityForConfirmedSession(
            sessions[1],
            [
                {
                    group_name: "Underdark",
                    user_name: "Player",
                    user_id: "current-user",
                    date: "2026-08-22",
                    status: "No",
                },
            ],
            "current-user"
        );

        expect(availabilityLabel(status)).toBe("Unavailable");
        expect(isConfirmedSessionMismatch(status)).toBe(true);
        expect(availabilityLabel(null)).toBe("Not answered");
    });
});
