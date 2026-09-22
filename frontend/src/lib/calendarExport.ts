import type { ConfirmedSession } from "@/services/api";

function compactDate(day: string): string {
    return day.replaceAll("-", "");
}

export function googleCalendarUrl(session: ConfirmedSession, groupName: string): string {
    const parameters = new URLSearchParams();
    parameters.set("action", "TEMPLATE");
    parameters.set("text", session.title || `Session — ${groupName}`);
    if (session.start_time && session.duration_minutes) {
        // The server resolves the group's wall time, including DST. Never fall
        // back to interpreting day + start_time in the browser's own timezone.
        const formatUtc = (instant: string | null | undefined) => {
            if (!instant || !/(Z|[+-]\d{2}:\d{2})$/.test(instant)) {
                throw new Error("Session calendar export requires server UTC instants");
            }
            return new Date(instant).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
        };
        parameters.set("dates", `${formatUtc(session.starts_at_utc)}/${formatUtc(session.ends_at_utc)}`);
    } else {
        const next = new Date(`${session.day}T00:00:00Z`);
        next.setUTCDate(next.getUTCDate() + 1);
        parameters.set("dates", `${compactDate(session.day)}/${compactDate(next.toISOString().slice(0, 10))}`);
    }
    if (session.notes) parameters.set("details", session.notes);
    return `https://calendar.google.com/calendar/render?${parameters.toString()}`;
}
