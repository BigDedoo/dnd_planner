import { Info } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { availabilityModeChoices } from "@/lib/availabilityMode";
import type { AvailabilityMode } from "@/services/api";

export function AvailabilityModeControl({ mode, updating, error, notice, onSwitch }: {
    mode: AvailabilityMode;
    updating: boolean;
    error: string | null;
    notice: string | null;
    onSwitch: (mode: AvailabilityMode) => void;
}) {
    return <div className="mb-3 min-w-0">
        <div className="flex min-w-0 flex-wrap items-center justify-start gap-x-2 gap-y-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Availability</h3>
            <div className="flex min-w-0 items-center gap-1.5">
                <Select value={mode} onValueChange={(value) => {
                    if (value !== mode) onSwitch(value as AvailabilityMode);
                }} disabled={updating}>
                    <SelectTrigger size="sm" aria-label="Availability mode" className="h-8 border-slate-600 bg-[#141c26] px-2.5 text-xs font-semibold text-amber-100 hover:border-amber-200/40 focus-visible:ring-amber-200/50">
                        <SelectValue>{mode === "global" ? "🌐 Global" : "👥 This group"}</SelectValue>
                    </SelectTrigger>
                    <SelectContent position="popper" align="end" className="border-slate-600 bg-[#1c2632] text-slate-100">
                        {availabilityModeChoices.map((choice) => <SelectItem key={choice.value} value={choice.value} className="text-xs focus:bg-amber-200/10 focus:text-amber-100">{choice.label}</SelectItem>)}
                    </SelectContent>
                </Select>
                <div className="group relative shrink-0">
                    <button type="button" aria-label="About availability modes" aria-describedby="availability-mode-help" className="flex size-8 items-center justify-center rounded-full text-slate-500 transition hover:text-amber-100 focus-visible:outline-2 focus-visible:outline-amber-200">
                        <Info aria-hidden="true" size={15} />
                    </button>
                    <div id="availability-mode-help" role="tooltip" className="pointer-events-none absolute right-0 top-full z-30 hidden w-56 max-w-[calc(100vw-2rem)] rounded-md border border-amber-200/20 bg-[#1c2632] p-2.5 text-[11px] leading-4 text-slate-200 shadow-xl group-hover:block group-focus-within:block">
                        <p>Global: your availability is shared across groups.</p>
                        <p className="mt-1">This group: availability is managed independently for this group.</p>
                    </div>
                </div>
            </div>
        </div>
        {notice && <p role="status" className="sr-only">{notice}</p>}
        {error && <p role="alert" className="mt-2 text-[11px] text-rose-200">{error}</p>}
    </div>;
}
