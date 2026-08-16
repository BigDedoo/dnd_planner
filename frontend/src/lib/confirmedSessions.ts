import type { MyConfirmedSession } from "@/services/api";

export function otherGroupConfirmedSessionsForDay(
    sessions: MyConfirmedSession[],
    currentGroupId: string,
    day: string
): MyConfirmedSession[] {
    return sessions.filter(
        (session) => session.group_id !== currentGroupId && session.day === day
    );
}

export function confirmedSessionReminderLabels(
    sessions: MyConfirmedSession[],
    currentGroupId: string,
    day: string
): string[] {
    return otherGroupConfirmedSessionsForDay(sessions, currentGroupId, day).map(
        (session) => `Session : ${session.group_name}`
    );
}
