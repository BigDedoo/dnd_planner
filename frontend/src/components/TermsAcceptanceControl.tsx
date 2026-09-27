import Link from "next/link";

export default function TermsAcceptanceControl({ checked, onChange, disabled, version }: {
    checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; version: string;
}) {
    return <div className="mt-6 space-y-3 text-sm text-slate-300">
        <label className="flex items-start gap-3">
            <input type="checkbox" required checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)} className="mt-1 size-4 shrink-0 accent-amber-300" />
            <span>I agree to the <Link href="/terms" target="_blank" rel="noopener" className="text-amber-200 underline">Terms of Use<span className="sr-only"> (opens a new tab)</span></Link>.</span>
        </label>
        <p className="text-xs text-slate-400">Version {version}. See how DnD Planner handles your data in the <Link href="/privacy" target="_blank" rel="noopener" className="text-amber-200 underline">Privacy Policy<span className="sr-only"> (opens a new tab)</span></Link>.</p>
    </div>;
}
