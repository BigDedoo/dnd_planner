import type { Availability, MyConfirmedSession } from "@/services/api";

export function upcomingConfirmedSessions(
    sessions: MyConfirmedSession[],
    today: string
): MyConfirmedSession[] {
    return sessions
        .filter((session) => session.day >= today)
        .sort(
            (left, right) =>
                left.day.localeCompare(right.day) ||
                left.group_name.localeCompare(right.group_name) ||
                left.id.localeCompare(right.id)
        );
}

export function sessionsForScheduleDay(
    sessions: MyConfirmedSession[],
    day: string
): MyConfirmedSession[] {
    return sessions.filter((session) => session.day === day);
}

export function nextUpcomingConfirmedSession(
    sessions: MyConfirmedSession[],
    today: string
): MyConfirmedSession | null {
    return upcomingConfirmedSessions(sessions, today)[0] ?? null;
}

export function availabilityForConfirmedSession(
    session: MyConfirmedSession,
    availability: Availability[],
    currentUserId: string | null
): string | null {
    if (!currentUserId) return null;
    return (
        availability.find(
            (entry) =>
                entry.user_id === currentUserId && entry.date === session.day
        )?.status ?? null
    );
}

export function availabilityLabel(status: string | null): string {
    if (status === "Available") return "Available";
    if (status === "Maybe") return "Maybe";
    if (status === "No") return "Unavailable";
    return "Not answered";
}

export function isConfirmedSessionMismatch(status: string | null): boolean {
    return status === "No";
}
