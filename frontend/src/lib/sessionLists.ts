import type { ConfirmedSession } from "@/services/api";

export function splitGroupSessions(sessions: ConfirmedSession[], today: string) {
    const active = sessions.filter((session) => !session.cancelled_at);
    return {
        upcoming: active.filter((session) => session.day >= today).sort(compareSessions),
        past: active.filter((session) => session.day < today).sort((a, b) => compareSessions(b, a)),
        cancelled: sessions.filter((session) => session.cancelled_at).sort((a, b) => compareSessions(b, a)),
    };
}

function compareSessions(left: ConfirmedSession, right: ConfirmedSession): number {
    return left.day.localeCompare(right.day) ||
        (left.start_time || "").localeCompare(right.start_time || "") ||
        left.id.localeCompare(right.id);
}
