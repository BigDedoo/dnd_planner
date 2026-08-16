import { describe, expect, it } from "vitest";

import {
    confirmedSessionReminderLabels,
    otherGroupConfirmedSessionsForDay,
} from "./confirmedSessions";

const sessions = [
    {
        id: "current-group-session",
        group_id: "group-current",
        group_name: "Fellowship",
        day: "2026-08-20",
        confirmed_by_user_id: "owner-current",
        confirmed_at: "2026-08-01T12:00:00Z",
    },
    {
        id: "underdark-session",
        group_id: "group-underdark",
        group_name: "Underdark",
        day: "2026-08-20",
        confirmed_by_user_id: "owner-underdark",
        confirmed_at: "2026-08-01T12:00:00Z",
    },
    {
        id: "avernus-session",
        group_id: "group-avernus",
        group_name: "Avernus",
        day: "2026-08-20",
        confirmed_by_user_id: "owner-avernus",
        confirmed_at: "2026-08-01T12:00:00Z",
    },
];

describe("cross-group confirmed session reminders", () => {
    it("shows another group's confirmed session while filling the current group", () => {
        expect(
            otherGroupConfirmedSessionsForDay(
                sessions,
                "group-current",
                "2026-08-20"
            )
        ).toEqual([sessions[1], sessions[2]]);
    });

    it("keeps every confirmed session on the same date visible", () => {
        expect(
            confirmedSessionReminderLabels(
                sessions,
                "group-current",
                "2026-08-20"
            )
        ).toEqual(["Session : Underdark", "Session : Avernus"]);
    });
});
