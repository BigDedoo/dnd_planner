import type { ConfirmedSession } from "@/services/api";

function compactDate(day: string): string {
    return day.replaceAll("-", "");
}

export function googleCalendarUrl(session: ConfirmedSession, groupName: string): string {
    const parameters = new URLSearchParams();
    parameters.set("action", "TEMPLATE");
    parameters.set("text", session.title || `Session — ${groupName}`);
    if (session.start_time && session.duration_minutes) {
        const start = new Date(`${session.day}T${session.start_time}`);
        const end = new Date(start.getTime() + session.duration_minutes * 60_000);
        const formatLocal = (value: Date) =>
            `${value.getFullYear()}${String(value.getMonth() + 1).padStart(2, "0")}${String(value.getDate()).padStart(2, "0")}T${String(value.getHours()).padStart(2, "0")}${String(value.getMinutes()).padStart(2, "0")}00`;
        parameters.set("dates", `${formatLocal(start)}/${formatLocal(end)}`);
    } else {
        const next = new Date(`${session.day}T00:00:00`);
        next.setDate(next.getDate() + 1);
        parameters.set("dates", `${compactDate(session.day)}/${compactDate(next.toISOString().slice(0, 10))}`);
    }
    if (session.notes) parameters.set("details", session.notes);
    return `https://calendar.google.com/calendar/render?${parameters.toString()}`;
}
