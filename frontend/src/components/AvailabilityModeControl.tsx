import type { AvailabilityMode } from "@/services/api";

export function AvailabilityModeControl({ mode, groupName, updating, error, notice, onSwitch }: {
    mode: AvailabilityMode;
    groupName: string;
    updating: boolean;
    error: string | null;
    notice: string | null;
    onSwitch: () => void;
}) {
    return <section aria-label="Your availability mode" className="mb-4 min-w-0 rounded-md border border-slate-700/80 bg-[#141c26]/70 px-3 py-2.5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Your availability</p>
                <p className="mt-0.5 text-xs font-semibold text-amber-100">{mode === "global" ? "Global availability" : "Separate for this group"}</p>
            </div>
            <button type="button" onClick={onSwitch} disabled={updating} className="min-h-10 rounded-md border border-amber-200/25 px-3 py-2 text-left text-xs font-bold text-amber-100 transition hover:bg-amber-200/10 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-amber-200">
                {updating ? "Updating..." : mode === "global" ? "Manage separately for this group" : "Use global availability"}
            </button>
        </div>
        <p className="mt-1.5 break-words text-[11px] leading-4 text-slate-400">
            {mode === "global"
                ? "Changes here are shared with every group where you use Global availability."
                : `Changes here affect only ${groupName}.`}
        </p>
        {notice && <p role="status" className="mt-2 text-[11px] text-emerald-200">{notice}</p>}
        {error && <p role="alert" className="mt-2 text-[11px] text-rose-200">{error}</p>}
    </section>;
}
