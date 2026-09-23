import Link from "next/link";
import { format, parseISO } from "date-fns";
import clsx from "clsx";

import type { Availability, MyConfirmedSession } from "@/services/api";
import {
    availabilityForConfirmedSession,
    availabilityLabel,
    groupSessionDayHref,
    isConfirmedSessionMismatch,
    rsvpLabel,
    sessionsForScheduleDay,
} from "@/lib/mySchedule";

export function MobileScheduleAgenda({ day, sessions, availability, currentUserId }: {
    day: string;
    sessions: MyConfirmedSession[];
    availability: Availability[];
    currentUserId: string | null;
}) {
    const selectedSessions = sessionsForScheduleDay(sessions, day);
    return <section aria-label="Selected day sessions" className="mt-4 rounded-lg border border-slate-700 bg-[#151d27] p-3 sm:hidden">
        <h3 className="font-serif text-base font-bold text-stone-100">{format(parseISO(day), "EEEE d MMMM")}</h3>
        {selectedSessions.length === 0 ? <p className="mt-2 text-sm text-slate-400">No sessions scheduled for this day.</p> :
            <div className="mt-3 space-y-2">
                {selectedSessions.map(session => {
                    const status = availabilityForConfirmedSession(session, availability, currentUserId);
                    const mismatch = isConfirmedSessionMismatch(status);
                    return <Link key={session.id} href={groupSessionDayHref(session)} className={clsx(
                        "block min-w-0 rounded-md border p-3 transition focus-visible:outline-2 focus-visible:outline-amber-200",
                        mismatch ? "border-rose-400/45 bg-rose-400/[0.07]" : "border-slate-700 bg-[#1a232e] hover:border-amber-200/50"
                    )}>
                        <p className="break-words font-semibold text-stone-100">{session.title || "Scheduled session"}</p>
                        <p className="mt-1 break-words text-xs text-amber-100">{session.group_name}</p>
                        {session.start_time && <p className="mt-1 text-xs text-slate-300">{session.start_time.slice(0, 5)}{session.group_timezone ? ` · ${session.group_timezone}` : ""}</p>}
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                            <span className="rounded-full bg-slate-700/80 px-2 py-0.5 text-slate-200">RSVP: {rsvpLabel(session.my_rsvp)}</span>
                            <span className="rounded-full bg-slate-700/80 px-2 py-0.5 text-slate-200">Availability: {availabilityLabel(status)}</span>
                            {mismatch && <span className="font-semibold text-rose-200">Availability conflict</span>}
                        </div>
                    </Link>;
                })}
            </div>}
    </section>;
}
