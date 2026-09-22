"use client";

import { useEffect, useState } from "react";
import { SurfacePanel } from "@/components/AppShell";
import { fetchNotificationPreferences, updateNotificationPreferences, type SessionReminderMinutes } from "@/services/api";

export const reminderOptions: { value: SessionReminderMinutes; label: string }[] = [
    { value: null, label: "Off" },
    { value: 60, label: "1 hour before" },
    { value: 180, label: "3 hours before" },
    { value: 720, label: "12 hours before" },
    { value: 1440, label: "1 day before" },
    { value: 4320, label: "3 days before" },
    { value: 10080, label: "7 days before" },
];

export function SessionReminderForm({ value, hasEmail, loading, saving, disabled, error, notice, onChange, onSave }: {
    value: SessionReminderMinutes; hasEmail: boolean; loading: boolean; saving: boolean; disabled: boolean;
    error: string | null; notice: string | null; onChange: (value: SessionReminderMinutes) => void; onSave: () => void;
}) {
    return <SurfacePanel className="space-y-3 p-5">
        <h2 className="font-serif text-xl text-stone-100">Notifications</h2>
        <p className="text-sm text-slate-400">We&apos;ll email you before timed sessions. Sessions you declined will not trigger a reminder.</p>
        {!hasEmail && <p className="text-sm text-amber-200">Delivery requires an email on your sign-in account. No reminder can be sent until one is available.</p>}
        <label className="block text-sm text-slate-300">Session reminder
            <select value={value ?? "off"} onChange={event => onChange(event.target.value === "off" ? null : Number(event.target.value) as SessionReminderMinutes)} disabled={loading || saving || disabled} className="mt-2 block w-full rounded-md border border-slate-600 bg-[#141c26] px-3 py-2 text-slate-100 focus:border-amber-200/70 disabled:opacity-50">
                {reminderOptions.map(option => <option key={option.value ?? "off"} value={option.value ?? "off"}>{option.label}</option>)}
            </select>
        </label>
        {loading && <p role="status" className="text-sm text-slate-400">Loading reminder preference…</p>}
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        {notice && <p role="status" className="text-sm text-emerald-300">{notice}</p>}
        <button onClick={onSave} disabled={loading || saving || disabled} className="rounded-md bg-[#d5a75b] px-4 py-2 text-sm font-bold text-[#18140f] hover:bg-[#e4bc77] disabled:opacity-50">{saving ? "Saving…" : "Save reminder"}</button>
    </SurfacePanel>;
}

export default function SessionReminderSettings({ email, getToken }: { email: string | null; getToken: () => Promise<string | null> }) {
    const [value, setValue] = useState<SessionReminderMinutes>(1440);
    const [loaded, setLoaded] = useState(false);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    useEffect(() => {
        let active = true;
        void (async () => {
            try {
                const result = await fetchNotificationPreferences(await getToken());
                if (active) { setValue(result.session_reminder_minutes); setLoaded(true); }
            } catch (failure) {
                if (active) setError(failure instanceof Error ? failure.message : "Could not load reminder preferences.");
            } finally { if (active) setLoading(false); }
        })();
        return () => { active = false; };
    }, [getToken]);
    const save = async () => {
        setSaving(true); setError(null); setNotice(null);
        try {
            const result = await updateNotificationPreferences(value, await getToken());
            setValue(result.session_reminder_minutes);
            setNotice("Session reminder updated.");
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : "Could not save reminder preference.");
        } finally { setSaving(false); }
    };
    return <SessionReminderForm value={value} hasEmail={Boolean(email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))} loading={loading} saving={saving} disabled={!loaded} error={error} notice={notice} onChange={next => { setValue(next); setNotice(null); }} onSave={() => void save()} />;
}
