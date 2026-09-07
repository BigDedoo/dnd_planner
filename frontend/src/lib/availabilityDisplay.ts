export function availabilityFillRateStyle(availableCount: number, memberCount: number) {
    if (memberCount <= 0) {
        return { dot: "bg-slate-500", text: "text-slate-400" };
    }

    const fillRate = availableCount / memberCount;
    if (fillRate <= 0.2) return { dot: "bg-rose-400/70", text: "text-rose-200" };
    if (fillRate <= 0.4) return { dot: "bg-orange-400/70", text: "text-orange-200" };
    if (fillRate <= 0.6) return { dot: "bg-amber-300/70", text: "text-amber-100" };
    if (fillRate <= 0.8) return { dot: "bg-lime-300/60", text: "text-lime-200" };
    return { dot: "bg-emerald-400/70", text: "text-emerald-200" };
}
