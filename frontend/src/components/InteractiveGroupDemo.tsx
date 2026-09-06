"use client";

import {
    addMonths,
    eachDayOfInterval,
    endOfMonth,
    format,
    getDay,
    isSameDay,
    isToday,
    startOfMonth,
    subMonths,
} from "date-fns";
import { CalendarDays, Check, ChevronLeft, ChevronRight, Clock3, Crown, Sparkles, Users, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ComponentProps, type FocusEvent, type ReactNode, type Ref } from "react";

import { bestDateReason, rankBestDates, type BestDateRecommendation } from "@/lib/bestDates";

type DemoFeature = "best-dates" | "calendar" | "details" | "schedule" | "rsvp";
type Availability = "Available" | "Maybe" | "No";
type DemoAvailability = Availability | null;
type Rsvp = "Going" | "Maybe" | "Declined";
type PopupPosition = { mode: "mobile" | "anchored"; top?: number; left?: number };
type PopupPlacement = { side: "above" | "below" | "left" | "right"; align: "start" | "end"; offsetX: number; offsetY: number };

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const demoMonth = new Date(2026, 7, 1);
const demoSessionDay = "2026-08-19";
const demoPlayers = [
    { name: "Daerrus", isYou: true },
    { name: "Lyra", isYou: false },
    { name: "Brom", isYou: false },
    { name: "Nessa", isYou: false },
    { name: "Trix", isYou: false },
] as const;
type DemoPlayerName = (typeof demoPlayers)[number]["name"];
type DayAvailability = Partial<Record<DemoPlayerName, DemoAvailability>>;

const seededAvailability: Record<string, DayAvailability> = {
    "2026-08-12": { Daerrus: "Maybe", Lyra: "Available", Brom: "No", Nessa: "Available", Trix: "Maybe" },
    "2026-08-15": { Daerrus: "Maybe", Lyra: "Available", Brom: "Available", Nessa: "Available", Trix: "Available" },
    "2026-08-16": { Daerrus: "Available", Lyra: "Maybe", Brom: "Available", Nessa: "No", Trix: "Available" },
    "2026-08-19": { Daerrus: "Available", Lyra: "Available", Brom: "Maybe", Nessa: "Available", Trix: "No" },
    "2026-08-21": { Daerrus: "No", Lyra: "Available", Brom: "Maybe", Nessa: "Available", Trix: "Maybe" },
    "2026-08-23": { Daerrus: "Available", Lyra: "Available", Brom: "Available", Nessa: "Maybe", Trix: "Available" },
    "2026-08-24": { Daerrus: "Maybe", Lyra: "No", Brom: "Available", Nessa: "Available", Trix: "Maybe" },
};

const explanations: Record<DemoFeature, { title: string; copy: string; detail: string }> = {
    "best-dates": { title: "Best Dates", copy: "See the strongest options before another long group-chat thread.", detail: "Recommendations update from the party’s availability." },
    calendar: { title: "Personal Availability", copy: "Let your party know when you could play: Available, Maybe, or Unavailable.", detail: "Change or clear your answer with the status control. Selecting a date only shows its details." },
    details: { title: "Group Availability", copy: "See who can play on the selected day before choosing a session date.", detail: "The party’s answers help you compare your options." },
    schedule: { title: "Schedule a Session", copy: "Turn a good date into a confirmed game with a time.", detail: "This demo confirmation stays only in your browser." },
    rsvp: { title: "Session RSVP", copy: "Availability says you could play; RSVP is your answer to a scheduled session.", detail: "Players can respond Going, Maybe, or Declined." },
};

const featureExplanationId = "landing-demo-feature-explanation";
const popupPlacements: Record<DemoFeature, PopupPlacement[]> = {
    "best-dates": [{ side: "above", align: "end", offsetX: -28, offsetY: -10 }, { side: "left", align: "start", offsetX: -16, offsetY: 8 }, { side: "above", align: "start", offsetX: 18, offsetY: -10 }],
    calendar: [{ side: "below", align: "start", offsetX: -46, offsetY: 16 }, { side: "left", align: "end", offsetX: -16, offsetY: 18 }, { side: "above", align: "start", offsetX: -26, offsetY: -12 }],
    details: [{ side: "right", align: "start", offsetX: 16, offsetY: 0 }, { side: "above", align: "end", offsetX: 0, offsetY: -12 }],
    schedule: [{ side: "above", align: "end", offsetX: 24, offsetY: -14 }, { side: "right", align: "start", offsetX: 16, offsetY: -12 }, { side: "above", align: "start", offsetX: 20, offsetY: -14 }],
    rsvp: [{ side: "below", align: "end", offsetX: 28, offsetY: 18 }, { side: "right", align: "end", offsetX: 16, offsetY: 16 }, { side: "below", align: "start", offsetX: 20, offsetY: 18 }],
};

export function InteractiveGroupDemo() {
    const [displayedMonth, setDisplayedMonth] = useState(demoMonth);
    const [selectedDate, setSelectedDate] = useState(new Date(2026, 7, 19));
    const [activeFeature, setActiveFeature] = useState<DemoFeature | null>(null);
    const [pinnedFeature, setPinnedFeature] = useState<DemoFeature | null>(null);
    const [availabilityByDay, setAvailabilityByDay] = useState(seededAvailability);
    const [scheduledDay, setScheduledDay] = useState<string | null>(demoSessionDay);
    const [rsvp, setRsvp] = useState<Rsvp>("Going");
    const [popupPosition, setPopupPosition] = useState<PopupPosition | null>(null);
    const surfaceRefs = useRef<Partial<Record<DemoFeature, HTMLDivElement | null>>>({});
    const popupRef = useRef<HTMLDivElement>(null);
    const hoverCloseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const feature = pinnedFeature ?? activeFeature;
    const selectedDayKey = format(selectedDate, "yyyy-MM-dd");
    const selectedDayAvailability = availabilityByDay[selectedDayKey] ?? {};
    const selectedDaySummary = getDaySummary(selectedDayKey, availabilityByDay);
    const monthStart = startOfMonth(displayedMonth);
    const daysInMonth = eachDayOfInterval({ start: monthStart, end: endOfMonth(displayedMonth) });
    const startPadding = Array.from({ length: (getDay(monthStart) + 6) % 7 });
    const bestDates = getBestDates(availabilityByDay, displayedMonth);

    const clearHoverCloseTimer = useCallback(() => {
        if (hoverCloseTimer.current) {
            clearTimeout(hoverCloseTimer.current);
            hoverCloseTimer.current = null;
        }
    }, []);

    const positionPopup = useCallback((nextFeature: DemoFeature) => {
        const element = surfaceRefs.current[nextFeature];
        if (!element) return;
        const rect = element.getBoundingClientRect();
        if (window.innerWidth < 768) {
            setPopupPosition({ mode: "mobile" });
            return;
        }

        const margin = 12;
        const gap = 12;
        const popupWidth = Math.min(304, window.innerWidth - margin * 2);
        const popupHeight = popupRef.current?.getBoundingClientRect().height ?? 180;
        const getCandidate = ({ side, align, offsetX, offsetY }: PopupPlacement) => {
            const left = align === "start" ? rect.left + offsetX : rect.right - popupWidth + offsetX;
            const top = side === "above" ? rect.top - popupHeight - gap + offsetY : side === "below" ? rect.bottom + gap + offsetY : align === "start" ? rect.top + offsetY : rect.bottom - popupHeight + offsetY;
            const adjustedLeft = side === "left" ? rect.left - popupWidth - gap + offsetX : side === "right" ? rect.right + gap + offsetX : left;
            return { top, left: adjustedLeft };
        };
        const candidates = popupPlacements[nextFeature].map(getCandidate);
        const fitsViewport = ({ top, left }: { top: number; left: number }) => top >= margin && left >= margin && top + popupHeight <= window.innerHeight - margin && left + popupWidth <= window.innerWidth - margin;
        const preferred = candidates.find(fitsViewport) ?? candidates[0];
        setPopupPosition({ mode: "anchored", top: Math.max(margin, Math.min(preferred.top, window.innerHeight - popupHeight - margin)), left: Math.max(margin, Math.min(preferred.left, window.innerWidth - popupWidth - margin)) });
    }, []);

    const revealFeature = useCallback((nextFeature: DemoFeature) => {
        clearHoverCloseTimer();
        setActiveFeature(nextFeature);
        positionPopup(nextFeature);
    }, [clearHoverCloseTimer, positionPopup]);
    const pinFeature = useCallback((nextFeature: DemoFeature) => {
        clearHoverCloseTimer();
        setActiveFeature(nextFeature);
        // Desktop clicks must not lock out subsequent hover descriptions.
        // Keep the existing pinned explanation for touch interaction.
        setPinnedFeature(window.innerWidth < 768 ? nextFeature : null);
        positionPopup(nextFeature);
    }, [clearHoverCloseTimer, positionPopup]);
    const dismissPopup = useCallback(() => {
        clearHoverCloseTimer();
        setActiveFeature(null);
        setPinnedFeature(null);
        setPopupPosition(null);
    }, [clearHoverCloseTimer]);
    const scheduleHoverDismiss = useCallback((nextFeature: DemoFeature) => {
        if (pinnedFeature === nextFeature) return;
        clearHoverCloseTimer();
        hoverCloseTimer.current = setTimeout(() => {
            setActiveFeature((current) => current === nextFeature ? null : current);
            hoverCloseTimer.current = null;
        }, 140);
    }, [clearHoverCloseTimer, pinnedFeature]);

    useEffect(() => {
        if (!feature) return;
        const frame = window.requestAnimationFrame(() => positionPopup(feature));
        const handleResize = () => positionPopup(feature);
        window.addEventListener("resize", handleResize);
        window.addEventListener("scroll", handleResize, true);
        return () => {
            window.cancelAnimationFrame(frame);
            window.removeEventListener("resize", handleResize);
            window.removeEventListener("scroll", handleResize, true);
        };
    }, [feature, positionPopup]);

    useEffect(() => {
        if (!feature) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") dismissPopup();
        };
        const handlePointerDown = (event: PointerEvent) => {
            if (!pinnedFeature) return;
            const target = event.target as Node;
            const trigger = surfaceRefs.current[pinnedFeature];
            if (!popupRef.current?.contains(target) && !trigger?.contains(target)) dismissPopup();
        };
        document.addEventListener("keydown", handleKeyDown);
        document.addEventListener("pointerdown", handlePointerDown);
        return () => {
            document.removeEventListener("keydown", handleKeyDown);
            document.removeEventListener("pointerdown", handlePointerDown);
        };
    }, [dismissPopup, feature, pinnedFeature]);

    useEffect(() => {
        if (pinnedFeature) popupRef.current?.focus();
    }, [pinnedFeature]);

    const handlePopupLeave = () => {
        if (feature && !pinnedFeature) scheduleHoverDismiss(feature);
    };
    const handlePopupEnter = () => {
        if (feature) revealFeature(feature);
    };
    const selectDate = (date: Date, source?: DemoFeature) => {
        setSelectedDate(date);
        if (source) pinFeature(source);
    };
    const cycleMyAvailability = (date: Date) => {
        const dateKey = format(date, "yyyy-MM-dd");
        setAvailabilityByDay((current) => {
            const previous = current[dateKey]?.Daerrus ?? null;
            const nextStatus: DemoAvailability = previous === "Available" ? "Maybe" : previous === "Maybe" ? "No" : previous === "No" ? null : "Available";
            return { ...current, [dateKey]: { ...current[dateKey], Daerrus: nextStatus } };
        });
    };
    const describedBy = (nextFeature: DemoFeature) => feature === nextFeature ? featureExplanationId : undefined;
    const setSurfaceRef = (nextFeature: DemoFeature) => (element: HTMLDivElement | null) => {
        surfaceRefs.current[nextFeature] = element;
    };
    const surfaceProps = (nextFeature: DemoFeature) => ({
        active: feature === nextFeature,
        setSurfaceRef: setSurfaceRef(nextFeature),
        onSurfaceEnter: () => revealFeature(nextFeature),
        onSurfaceLeave: () => scheduleHoverDismiss(nextFeature),
        onSurfaceFocus: () => revealFeature(nextFeature),
        onSurfaceBlur: (event: FocusEvent<HTMLDivElement>) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) scheduleHoverDismiss(nextFeature);
        },
        onSurfacePin: () => pinFeature(nextFeature),
    });

    return (
        <section id="demo" className="relative z-10 mx-auto max-w-7xl px-4 pb-16 sm:px-6 sm:pb-20" aria-labelledby="demo-heading">
            <div className="mb-5 text-center"><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/70">Interactive product preview</p><h2 id="demo-heading" className="mt-2 font-serif text-2xl font-bold text-stone-100 sm:text-3xl">From availability to game night.</h2><p className="mx-auto mt-2 max-w-2xl text-sm text-slate-400">Explore a small, static version of the group experience. Nothing here is connected to a real campaign.</p></div>
            <div className="overflow-hidden rounded-2xl border border-slate-600/80 bg-[#18212c] shadow-[0_28px_80px_rgba(0,0,0,0.48)]">
                <div className="flex items-center justify-between border-b border-slate-700/70 bg-[#202a36] px-3 py-2.5 sm:px-4"><div className="flex items-center gap-2 text-xs font-bold text-slate-200"><span className="size-2 rounded-full bg-emerald-400" /> The party is planning</div><span className="rounded border border-slate-600 bg-[#161e28] px-2 py-1 text-[10px] text-slate-400">Interactive demo</span></div>
                <div className="p-3 sm:p-5">
                    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_250px]">
                        <DemoSurface className="p-4" {...surfaceProps("best-dates")}>
                            <div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/70">Group planning</p><h3 className="mt-1 font-serif text-lg font-bold text-amber-50">Best Dates</h3><p className="mt-1 text-[11px] text-slate-400">The party’s strongest options this month.</p></div><Sparkles size={18} className="text-amber-200/70" /></div>
                            <div className="mt-3 grid gap-1.5 sm:grid-cols-3">{bestDates.length > 0 ? bestDates.map((recommendation) => <button key={recommendation.day} type="button" aria-describedby={describedBy("best-dates")} onClick={() => selectDate(parseDemoDate(recommendation.day), "best-dates")} className={demoButtonClass(selectedDayKey === recommendation.day)}><span className="font-bold text-slate-100">{format(parseDemoDate(recommendation.day), "EEE d MMM")}</span><span className="text-[10px] text-emerald-300">{bestDateReason(recommendation, demoPlayers.length)}</span></button>) : <p className="rounded-md border border-slate-700 bg-[#141c26]/60 px-3 py-2 text-xs text-slate-500 sm:col-span-3">No recommendations for this month yet.</p>}</div>
                        </DemoSurface>
                        <DemoSurface active={false} className="p-4"><div className="flex items-center gap-2"><Users size={16} className="text-amber-200/70" /><h3 className="text-sm font-bold text-stone-100">Group Context</h3></div><div className="mt-3 flex flex-wrap items-center gap-2"><p className="font-serif text-xl font-bold text-stone-100">Green Flag</p><span className="inline-flex items-center gap-1 rounded-full border border-amber-200/25 bg-amber-200/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-100"><Crown size={11} /> Owner</span></div><p className="mt-3 text-xs text-slate-400">Timezone: <strong className="text-slate-200">Europe/Paris</strong></p><p className="mt-1 text-xs text-slate-400">Playing as: <strong className="text-amber-100">Daerrus</strong></p></DemoSurface>
                    </div>
                    <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_250px]">
                        <DemoSurface className="p-4 sm:p-5" active={feature === "calendar"} setSurfaceRef={setSurfaceRef("calendar")}>
                            <div className="flex flex-col gap-3"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><CalendarDays size={18} className="text-amber-200" /><div><h3 className="font-serif text-lg font-bold text-stone-100">Group Calendar</h3><p className="text-[10px] text-slate-500">Select a date to inspect it. Use its small status control to update your answer.</p></div></div><div className="hidden items-center gap-2 text-[10px] text-slate-400 sm:flex"><span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-emerald-400" /> Available</span><span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-amber-300" /> Maybe</span><span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-rose-400" /> No</span></div></div><div className="flex flex-wrap items-center gap-1 self-start rounded-lg border border-slate-700 bg-[#141c26] p-1 text-xs text-slate-300 sm:self-end"><MonthButton label="Previous year" onClick={() => setDisplayedMonth((current) => subMonths(current, 12))}>«</MonthButton><MonthButton label="Previous month" onClick={() => setDisplayedMonth((current) => subMonths(current, 1))}><ChevronLeft size={14} /></MonthButton><span className="min-w-28 border-x border-slate-700 px-2.5 py-1 text-center font-semibold">{format(displayedMonth, "MMMM yyyy")}</span><MonthButton label="Next month" onClick={() => setDisplayedMonth((current) => addMonths(current, 1))}><ChevronRight size={14} /></MonthButton><MonthButton label="Next year" onClick={() => setDisplayedMonth((current) => addMonths(current, 12))}>»</MonthButton><button type="button" onClick={() => { const today = new Date(); setDisplayedMonth(today); setSelectedDate(today); }} className="rounded-md px-2 py-1 text-[10px] font-bold text-amber-100 transition hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-200/70">Today</button></div></div>
                            <div className="mt-4 grid grid-cols-7 gap-1.5 sm:gap-2">{weekdays.map((day) => <div key={day} className="pb-1 text-center text-[9px] font-bold uppercase tracking-wide text-slate-500">{day}</div>)}{startPadding.map((_, index) => <div key={`blank-${index}`} className="min-h-[58px] rounded-md border border-transparent bg-[#141c26]/40 sm:min-h-[82px]" />)}{daysInMonth.map((date) => { const dateKey = format(date, "yyyy-MM-dd"); return <CalendarDay key={dateKey} date={date} selected={isSameDay(date, selectedDate)} scheduled={scheduledDay === dateKey} recommended={bestDates.some((recommendation) => recommendation.day === dateKey)} summary={getDaySummary(dateKey, availabilityByDay)} youAvailability={availabilityByDay[dateKey]?.Daerrus ?? null} availabilityHint={surfaceProps("calendar")} describedBy={describedBy("calendar")} onSelect={() => selectDate(date)} onCycleAvailability={() => cycleMyAvailability(date)} />; })}</div>
                        </DemoSurface>
                        <div className="space-y-3">
                            <DemoSurface className="p-4" {...surfaceProps("details")} setSurfaceRef={(element) => { surfaceRefs.current.details = element; surfaceRefs.current.schedule = element; }}><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/70">Selected day</p><h3 className="mt-1 font-serif text-lg font-bold text-stone-100">{format(selectedDate, "EEEE, MMMM d")}</h3>{scheduledDay === selectedDayKey ? <button data-demo-feature="schedule" type="button" onPointerEnter={() => revealFeature("schedule")} onPointerLeave={() => scheduleHoverDismiss("schedule")} onFocus={(event) => { event.stopPropagation(); revealFeature("schedule"); }} aria-describedby={describedBy("schedule")} onClick={() => pinFeature("rsvp")} className="mt-3 w-full rounded-md border border-amber-200/25 bg-amber-200/[0.09] px-3 py-2 text-left text-xs text-amber-100 transition hover:border-amber-200/55 focus:outline-none focus:ring-2 focus:ring-amber-200/70"><p className="font-bold">✓ Green Flag session</p><p className="mt-1 flex items-center gap-1 text-[11px] text-amber-100/80"><Clock3 size={12} /> 19:00 – 23:00 · View RSVP</p></button> : <p className="mt-3 rounded-md border border-slate-700 bg-[#141c26]/70 px-3 py-2 text-xs text-slate-400">No session is confirmed yet.</p>}<div className="mt-3 border-t border-slate-700/60 pt-3"><div className="flex items-center justify-between gap-2"><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">Party availability</p><span className="text-[10px] font-semibold text-emerald-300">{selectedDaySummary?.label ?? "No responses yet"}</span></div><div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">{demoPlayers.map((player) => <div key={player.name} className={`flex min-w-0 items-center justify-between gap-2 rounded px-1 py-0.5 text-[11px] ${player.isYou ? "bg-amber-200/[0.07]" : ""}`}><span className="truncate text-slate-300">{player.name}{player.isYou && <span className="ml-1 text-[9px] font-bold uppercase tracking-wide text-amber-200/75">You</span>}</span><AvailabilityStatus status={selectedDayAvailability[player.name] ?? null} /></div>)}</div></div><button data-demo-feature="schedule" type="button" onPointerEnter={() => revealFeature("schedule")} onPointerLeave={() => scheduleHoverDismiss("schedule")} onFocus={(event) => { event.stopPropagation(); revealFeature("schedule"); }} aria-describedby={describedBy("schedule")} onClick={() => { setScheduledDay((day) => day === selectedDayKey ? null : selectedDayKey); pinFeature("schedule"); }} className="mt-3 w-full rounded-md bg-[#d5a75b] px-3 py-2 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77]">{scheduledDay === selectedDayKey ? "Edit session details" : "Schedule this session"}</button></DemoSurface>
                            <DemoSurface className="p-4" {...surfaceProps("rsvp")}><div className="flex items-center justify-between gap-2"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">Roster / RSVP</p><h3 className="mt-1 font-serif text-base font-bold text-stone-100">Who is coming?</h3></div><span className="text-[10px] font-bold text-emerald-300">4 going</span></div><div className="mt-3 space-y-2">{demoPlayers.filter((player) => !player.isYou).map((player) => <RosterRow key={player.name} name={player.name} status="Going" />)}<RosterRow name="Daerrus (you)" status={rsvp} /></div><div className="mt-3 flex gap-1.5">{(["Going", "Maybe", "Declined"] as Rsvp[]).map((status) => <button key={status} type="button" aria-describedby={describedBy("rsvp")} onClick={() => { setRsvp(status); pinFeature("rsvp"); }} className={`flex-1 rounded-md px-1.5 py-1.5 text-[10px] font-bold transition ${rsvp === status ? rsvpTone(status) : "bg-slate-800 text-slate-400 hover:text-slate-200"}`}>{status === "Declined" ? "No" : status}</button>)}</div></DemoSurface>
                        </div>
                    </div>
                </div>
            </div>
            {feature && popupPosition && <FeaturePopover ref={popupRef} feature={feature} position={popupPosition} onClose={dismissPopup} onMouseEnter={handlePopupEnter} onMouseLeave={handlePopupLeave} />}
        </section>
    );
}

type DemoSurfaceProps = ComponentProps<"div"> & { active: boolean; setSurfaceRef?: (element: HTMLDivElement | null) => void; onSurfaceEnter?: () => void; onSurfaceLeave?: () => void; onSurfaceFocus?: () => void; onSurfaceBlur?: (event: FocusEvent<HTMLDivElement>) => void; onSurfacePin?: () => void };

function DemoSurface({ active, className, children, setSurfaceRef, onSurfaceEnter, onSurfaceLeave, onSurfaceFocus, onSurfaceBlur, onSurfacePin, ...props }: DemoSurfaceProps) {
    return <div ref={setSurfaceRef} onPointerEnter={onSurfaceEnter} onPointerLeave={onSurfaceLeave} onFocusCapture={onSurfaceFocus} onBlurCapture={onSurfaceBlur} onClick={(event) => { if (!(event.target as HTMLElement).closest("[data-demo-feature]")) onSurfacePin?.(); }} className={`relative rounded-xl border bg-[#1a232e] shadow-[0_12px_28px_rgba(0,0,0,0.16)] transition duration-200 ${active ? "border-amber-200/65 bg-amber-200/[0.07] shadow-[0_0_0_1px_rgba(224,182,110,0.16),0_14px_32px_rgba(0,0,0,0.22)]" : "border-slate-700/80"} ${className ?? ""}`} {...props}>{children}</div>;
}

function FeaturePopover({ feature, position, onClose, onMouseEnter, onMouseLeave, ref }: { feature: DemoFeature; position: PopupPosition; onClose: () => void; onMouseEnter: () => void; onMouseLeave: () => void; ref: Ref<HTMLDivElement> }) {
    const explanation = explanations[feature];
    return <div ref={ref} id={featureExplanationId} role="dialog" aria-label={explanation.title} tabIndex={-1} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave} className={`fixed z-[100] rounded-xl border border-amber-200/25 bg-[#151d27]/[0.98] p-4 text-left shadow-[0_18px_48px_rgba(0,0,0,0.42),0_0_0_1px_rgba(224,182,110,0.06)] outline-none backdrop-blur-md ${position.mode === "mobile" ? "bottom-3 left-3 right-3 w-auto" : "pointer-events-none w-[19rem]"}`} style={position.mode === "anchored" ? { top: position.top, left: position.left } : undefined}><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200/70">Interactive guide</p><p className="mt-1 font-serif text-base font-bold text-stone-100">{explanation.title}</p></div><button type="button" aria-label="Close explanation" onClick={onClose} className={`${position.mode === "anchored" ? "hidden" : ""} rounded-md p-1 text-slate-400 transition hover:bg-slate-700/60 hover:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-200/70`}><X size={15} /></button></div><p className="mt-2 text-xs leading-5 text-slate-300">{explanation.copy}</p><p className="mt-1 text-[11px] leading-4 text-slate-500">{explanation.detail}</p></div>;
}

function MonthButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
    return <button type="button" aria-label={label} onClick={onClick} className="rounded-md px-1.5 py-1 text-slate-300 transition hover:bg-slate-700 hover:text-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-200/70">{children}</button>;
}

function CalendarDay({ date, selected, scheduled, recommended, summary, youAvailability, availabilityHint, describedBy, onSelect, onCycleAvailability }: { date: Date; selected: boolean; scheduled: boolean; recommended: boolean; summary: DaySummary | null; youAvailability: DemoAvailability; availabilityHint: DemoSurfaceProps; describedBy?: string; onSelect: () => void; onCycleAvailability: () => void }) {
    const currentDay = isToday(date);
    const dateLabel = format(date, "MMMM d");
    return <div role="button" tabIndex={0} aria-label={`Select ${dateLabel}`} onClick={onSelect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(); } }} className={`relative flex min-h-[58px] cursor-pointer flex-col justify-between rounded-md border p-1.5 text-left transition focus:outline-none focus:ring-2 focus:ring-amber-200/70 sm:min-h-[82px] sm:p-2 ${selected ? "border-amber-200 bg-amber-200/[0.09] ring-1 ring-amber-200/70" : scheduled ? "border-amber-300/55 bg-amber-200/[0.05] hover:border-amber-200" : recommended ? "border-emerald-400/30 bg-emerald-400/[0.06] hover:border-emerald-300/45" : "border-slate-700/80 bg-[#151d27] hover:border-slate-600"} ${currentDay ? "font-bold shadow-[inset_0_0_0_1px_rgba(96,165,250,0.35)]" : ""}`}><div className="flex items-center justify-between"><span className={`flex size-5 items-center justify-center rounded-full text-[10px] font-bold ${currentDay ? "bg-sky-400 text-slate-950" : "text-slate-300"}`}>{format(date, "d")}</span><button type="button" aria-describedby={describedBy} onPointerEnter={availabilityHint.onSurfaceEnter} onPointerLeave={availabilityHint.onSurfaceLeave} onFocus={availabilityHint.onSurfaceFocus} onBlur={() => availabilityHint.onSurfaceLeave?.()} aria-label={`Cycle your availability for ${dateLabel}`} title={`Cycle availability: ${nextAvailabilityLabel(youAvailability)}`} onClick={(event) => { event.stopPropagation(); onCycleAvailability(); }} onKeyDown={(event) => event.stopPropagation()} className={`rounded px-1.5 py-0.5 text-[10px] font-extrabold transition hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-200/70 ${availabilityButtonTone(youAvailability)}`}>{availabilitySymbol(youAvailability)}</button></div><div className="mt-1 space-y-1">{scheduled && <div className="rounded bg-amber-200/14 px-1 py-0.5 text-center text-[8px] font-bold text-amber-100 sm:text-[9px]">✓ 19:00</div>}{summary && <>{summary.availableCount > 0 ? <div className="text-center text-[9px] font-semibold text-emerald-300 sm:text-[10px]">🟢 {summary.availableCount}/{demoPlayers.length}</div> : summary.maybeCount > 0 ? <div className="text-center text-[9px] font-semibold text-amber-200 sm:text-[10px]">🟡 {summary.maybeCount} maybe</div> : summary.noCount > 0 ? <div className="text-center text-[9px] font-semibold text-slate-500 sm:text-[10px]">{summary.noCount} no</div> : null}<div className="flex justify-center gap-0.5">{demoPlayers.map((player) => <span key={player.name} className={`size-1.5 rounded-full ${availabilityDot(summary.statuses[player.name] ?? null)}`} />)}</div></>}</div></div>;
}

type DaySummary = { availableCount: number; maybeCount: number; noCount: number; label: string; statuses: DayAvailability };

function getDaySummary(day: string, availability: Record<string, DayAvailability>): DaySummary | null {
    const statuses = availability[day];
    if (!statuses) return null;
    const availableCount = demoPlayers.filter((player) => statuses[player.name] === "Available").length;
    const maybeCount = demoPlayers.filter((player) => statuses[player.name] === "Maybe").length;
    const noCount = demoPlayers.filter((player) => statuses[player.name] === "No").length;
    return { availableCount, maybeCount, noCount, label: `${availableCount}/${demoPlayers.length} available`, statuses };
}

function getBestDates(availability: Record<string, DayAvailability>, displayedMonth: Date): BestDateRecommendation[] {
    const entries = Object.entries(availability).flatMap(([date, statuses]) => demoPlayers.flatMap((player) => {
        const status = statuses[player.name];
        return status ? [{ group_name: "Green Flag", user_name: player.name, date, status }] : [];
    }));
    return rankBestDates(entries, demoPlayers.length, format(startOfMonth(displayedMonth), "yyyy-MM-dd"));
}

function parseDemoDate(day: string) { return new Date(`${day}T12:00:00`); }
function availabilityDot(status: DemoAvailability) { return status === "Available" ? "bg-emerald-400" : status === "Maybe" ? "bg-amber-300" : status === "No" ? "bg-rose-400" : "bg-slate-600"; }
function availabilitySymbol(status: DemoAvailability) { return status === "Available" ? "✓" : status === "Maybe" ? "?" : status === "No" ? "✗" : "·"; }
function nextAvailabilityLabel(status: DemoAvailability) { return status === "Available" ? "Maybe" : status === "Maybe" ? "Unavailable" : status === "No" ? "Clear" : "Available"; }
function availabilityButtonTone(status: DemoAvailability) { return status === "Available" ? "bg-emerald-400/15 text-emerald-200" : status === "Maybe" ? "bg-amber-300/15 text-amber-100" : status === "No" ? "bg-rose-400/15 text-rose-200" : "text-slate-500 hover:text-amber-100"; }
function AvailabilityStatus({ status }: { status: DemoAvailability }) { return <span className={`shrink-0 text-[9px] font-semibold ${status === "Available" ? "text-emerald-300" : status === "Maybe" ? "text-amber-100" : status === "No" ? "text-rose-200" : "text-slate-600"}`}>{status === "No" ? "No" : status ?? "Unset"}</span>; }
function RosterRow({ name, status }: { name: string; status: Rsvp }) { return <div className="flex items-center justify-between border-b border-slate-700/60 pb-2 text-xs"><span className="text-slate-300">{name}</span><span className={`flex items-center gap-1 text-[10px] font-semibold ${status === "Going" ? "text-emerald-300" : status === "Maybe" ? "text-amber-100" : "text-rose-200"}`}>{status === "Going" ? <Check size={11} /> : <X size={11} />}{status}</span></div>; }
function demoButtonClass(selected: boolean) { return `flex items-center justify-between gap-2 rounded-md border px-2.5 py-2 text-left text-xs transition focus:outline-none focus:ring-2 focus:ring-amber-200/70 ${selected ? "border-amber-200/55 bg-amber-200/[0.12]" : "border-amber-200/15 bg-[#141c26]/60 hover:border-amber-200/40 hover:bg-amber-200/10"}`; }
function rsvpTone(status: Rsvp) { return status === "Going" ? "bg-emerald-400/15 text-emerald-200" : status === "Maybe" ? "bg-amber-300/15 text-amber-100" : "bg-rose-400/15 text-rose-200"; }
