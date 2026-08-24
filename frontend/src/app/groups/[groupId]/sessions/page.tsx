"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton, useAuth } from "@clerk/nextjs";
import { CalendarDays, ChevronLeft, Clock3, Download } from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { googleCalendarUrl } from "@/lib/calendarExport";
import { splitGroupSessions } from "@/lib/sessionLists";
import {
    ConfirmedSession,
    downloadGroupSessionIcs,
    fetchGroupConfirmedSessions,
    fetchGroupDetail,
    fetchOnboardingStatus,
    GroupDetail,
    SessionRsvpStatus,
    updateOwnSessionRsvp,
} from "@/services/api";

const FIRST_DAY = "2000-01-01";
const LAST_DAY = "2100-12-31";

function todayIso() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export default function GroupSessionsPage({ params }: { params: Promise<{ groupId: string }> }) {
    const { groupId } = use(params);
    const { getToken, isLoaded } = useAuth();
    const router = useRouter();
    const [group, setGroup] = useState<GroupDetail | null>(null);
    const [sessions, setSessions] = useState<ConfirmedSession[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [updatingId, setUpdatingId] = useState<string | null>(null);

    const load = useCallback(async () => {
        const token = await getToken();
        const onboarding = await fetchOnboardingStatus(token);
        if (!onboarding.linked) {
            router.replace(`/onboarding?next=/groups/${groupId}/sessions`);
            return;
        }
        const [detail, rows] = await Promise.all([
            fetchGroupDetail(groupId, token),
            fetchGroupConfirmedSessions(groupId, FIRST_DAY, LAST_DAY, token, true),
        ]);
        setGroup(detail);
        setSessions(rows);
    }, [getToken, groupId, router]);

    useEffect(() => {
        if (!isLoaded) return;
        void load().catch(() => setError("Could not load this group's sessions."));
    }, [isLoaded, load]);

    const updateRsvp = async (session: ConfirmedSession, status: SessionRsvpStatus) => {
        try {
            setUpdatingId(session.id);
            const token = await getToken();
            const updated = await updateOwnSessionRsvp(groupId, session.day, status, token);
            setSessions((current) => current.map((item) => item.id === updated.id ? updated : item));
        } catch {
            setError("Could not update your RSVP. Please retry.");
        } finally {
            setUpdatingId(null);
        }
    };

    const exportSession = async (session: ConfirmedSession) => {
        try {
            await downloadGroupSessionIcs(groupId, session.day, await getToken());
        } catch {
            setError("Could not download this calendar event.");
        }
    };

    const lists = splitGroupSessions(sessions, todayIso());
    const canManage = group?.role === "owner" || group?.role === "organizer";

    return <div className="min-h-screen bg-[#111820] text-slate-100">
        <header className="border-b border-slate-700/70 bg-[#141c26]">
            <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
                <Link href={`/groups/${groupId}`} className="flex items-center gap-2 text-sm font-bold text-amber-100"><ChevronLeft size={16} /> Group calendar</Link>
                <div className="flex items-center gap-3"><ThemeToggle /><UserButton /></div>
            </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
            <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
                <div><p className="text-xs font-bold uppercase tracking-widest text-amber-200/70">{group?.name || "Group"}</p><h1 className="mt-1 font-serif text-3xl font-bold">Sessions</h1><p className="mt-2 text-sm text-slate-400">Scheduled sessions and your RSVP are separate from day availability.</p></div>
                <Link href={`/groups/${groupId}`} className="rounded-md border border-slate-600 px-3 py-2 text-xs font-bold text-slate-200">Open calendar</Link>
            </div>
            {error && <p className="mb-5 rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-200">{error}</p>}
            <div className="space-y-8">
                <SessionSection title="Upcoming" sessions={lists.upcoming} empty="No upcoming sessions." groupName={group?.name || "Group"} groupId={groupId} canManage={canManage} updatingId={updatingId} onRsvp={updateRsvp} onExport={exportSession} />
                <SessionSection title="Past" sessions={lists.past} empty="No past sessions." groupName={group?.name || "Group"} groupId={groupId} canManage={false} updatingId={updatingId} onRsvp={updateRsvp} onExport={exportSession} />
                <SessionSection title="Cancelled" sessions={lists.cancelled} empty="No cancelled sessions." groupName={group?.name || "Group"} groupId={groupId} canManage={false} updatingId={updatingId} onRsvp={updateRsvp} onExport={exportSession} cancelled />
            </div>
        </main>
    </div>;
}

function SessionSection({ title, sessions, empty, groupName, groupId, canManage, updatingId, onRsvp, onExport, cancelled = false }: {
    title: string; sessions: ConfirmedSession[]; empty: string; groupName: string; groupId: string; canManage: boolean; updatingId: string | null;
    onRsvp: (session: ConfirmedSession, status: SessionRsvpStatus) => Promise<void>;
    onExport: (session: ConfirmedSession) => Promise<void>; cancelled?: boolean;
}) {
    return <section><h2 className="mb-3 font-serif text-xl font-bold text-stone-100">{title}</h2>{sessions.length === 0 ? <p className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-500">{empty}</p> : <div className="grid gap-3 lg:grid-cols-2">{sessions.map((session) => {
        const going = session.rsvps?.filter((rsvp) => rsvp.status === "going").length || 0;
        const maybe = session.rsvps?.filter((rsvp) => rsvp.status === "maybe").length || 0;
        const declined = session.rsvps?.filter((rsvp) => rsvp.status === "declined").length || 0;
        return <article key={session.id} className={`rounded-xl border p-4 ${cancelled ? "border-slate-700 bg-slate-900/40 opacity-70" : "border-slate-700 bg-[#18212c]"}`}>
            <div className="flex items-start justify-between gap-3"><div><p className="font-serif text-lg font-bold text-stone-100">{session.title || "DnD session"}</p><p className="mt-1 flex items-center gap-2 text-xs text-slate-300"><CalendarDays size={13} /> {session.day}{session.start_time && <><Clock3 size={13} className="ml-1" /> {session.start_time.slice(0, 5)}</>}</p></div><span className="rounded bg-slate-800 px-2 py-1 text-[10px] font-bold uppercase text-slate-400">{session.my_rsvp ? session.my_rsvp : "No RSVP"}</span></div>
            <p className="mt-3 text-xs text-slate-400">RSVP: {going} going · {maybe} maybe · {declined} declined</p>
            {!cancelled && <div className="mt-4 flex flex-wrap gap-2">{(["going", "maybe", "declined"] as SessionRsvpStatus[]).map((status) => <button key={status} disabled={updatingId === session.id} onClick={() => void onRsvp(session, status)} className={`rounded-md px-2.5 py-1.5 text-xs font-bold ${session.my_rsvp === status ? "bg-amber-200/20 text-amber-100" : "bg-slate-800 text-slate-300"}`}>{status === "going" ? "Going" : status === "maybe" ? "Maybe" : "Declined"}</button>)}<button onClick={() => void onExport(session)} className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-bold text-slate-300"><Download size={12} /> ICS</button><a href={googleCalendarUrl(session, groupName)} target="_blank" rel="noreferrer" className="rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-bold text-slate-300">Google Calendar</a>{canManage && <Link href={`/groups/${groupId}?day=${session.day}`} className="rounded-md bg-[#d5a75b] px-2.5 py-1.5 text-xs font-bold text-[#18140f]">Manage</Link>}</div>}
        </article>;
    })}</div>}</section>;
}
