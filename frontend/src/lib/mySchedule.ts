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
                (left.start_time || "99:99").localeCompare(right.start_time || "99:99") ||
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

export function groupSessionDayHref(session: MyConfirmedSession): string {
    return `/groups/${session.group_id}?day=${session.day}`;
}

export function rsvpLabel(status: MyConfirmedSession["my_rsvp"]): string {
    if (status === "going") return "Going";
    if (status === "maybe") return "Maybe";
    if (status === "declined") return "Declined";
    return "No RSVP";
}

export function selectedScheduleDayForMonth(
    selectedDay: string,
    displayedMonth: string,
    today: string
): string {
    if (selectedDay.startsWith(displayedMonth)) return selectedDay;
    return today.startsWith(displayedMonth) ? today : `${displayedMonth}-01`;
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
                entry.group_id === session.group_id && entry.user_id === currentUserId && entry.date === session.day
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
