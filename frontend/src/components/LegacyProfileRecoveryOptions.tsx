import { ArrowLeft, ShieldCheck, Users } from "lucide-react";

import { recoveryGroupSummary } from "../lib/legacyProfileRecovery";
import type { LegacyRecoveryProfile } from "../services/api";

type RecoveryChoiceProps = {
    onCreate: () => void;
    onRecover: () => void;
};

export function LegacyRecoveryChoice({
    onCreate,
    onRecover,
}: RecoveryChoiceProps) {
    return (
        <div className="mt-6 space-y-4">
            <section className="rounded-lg border border-amber-200/25 bg-amber-200/[0.07] p-4">
                <div className="flex items-start gap-3">
                    <ShieldCheck
                        size={19}
                        className="mt-0.5 shrink-0 text-amber-200"
                    />
                    <div>
                        <h2 className="font-serif text-lg font-bold text-stone-100">
                            Already played with us?
                        </h2>
                        <p className="mt-1 text-xs leading-5 text-slate-400">
                            Recover your existing profile and keep its groups and
                            planning data.
                        </p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={onRecover}
                    className="mt-4 w-full rounded-md bg-[#d5a75b] px-4 py-2.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77]"
                >
                    Recover existing profile
                </button>
            </section>
            <section className="rounded-lg border border-slate-700 bg-[#141c26]/70 p-4">
                <h2 className="font-serif text-base font-bold text-stone-100">
                    New here?
                </h2>
                <p className="mt-1 text-xs text-slate-400">
                    Create a fresh DnD Planner profile.
                </p>
                <button
                    type="button"
                    onClick={onCreate}
                    className="mt-3 text-xs font-bold text-amber-200 transition hover:text-amber-100"
                >
                    Create a new profile
                </button>
            </section>
        </div>
    );
}

type RecoveryProfileListProps = {
    profiles: LegacyRecoveryProfile[];
    onBack: () => void;
    onCreate: () => void;
    onSelect: (profile: LegacyRecoveryProfile) => void;
};

export function LegacyRecoveryProfileList({
    profiles,
    onBack,
    onCreate,
    onSelect,
}: RecoveryProfileListProps) {
    return (
        <div className="mt-6">
            <button
                type="button"
                onClick={onBack}
                className="inline-flex items-center gap-1 text-xs font-bold text-slate-400 transition hover:text-slate-200"
            >
                <ArrowLeft size={13} /> Back
            </button>
            <h2 className="mt-4 font-serif text-xl font-bold text-stone-100">
                Choose your existing profile
            </h2>
            <p className="mt-1 text-xs leading-5 text-slate-400">
                Use your name and groups to identify the right profile.
            </p>
            <div className="mt-4 space-y-2">
                {profiles.map((profile) => (
                    <button
                        key={profile.user_id}
                        type="button"
                        onClick={() => onSelect(profile)}
                        className="flex w-full items-center gap-3 rounded-lg border border-slate-700 bg-[#141c26]/70 p-3 text-left transition hover:border-amber-200/45 hover:bg-amber-200/[0.05] focus:outline-none focus:ring-2 focus:ring-amber-200/70"
                    >
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-slate-700 text-amber-100">
                            <Users size={17} />
                        </span>
                        <span className="min-w-0">
                            <span className="block font-bold text-stone-100">
                                {profile.display_name}
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-slate-400">
                                {recoveryGroupSummary(profile)}
                            </span>
                        </span>
                    </button>
                ))}
            </div>
            <button
                type="button"
                onClick={onCreate}
                className="mt-5 text-xs font-bold text-amber-200 transition hover:text-amber-100"
            >
                Create a new profile instead
            </button>
        </div>
    );
}

type RecoveryConfirmationProps = {
    isSubmitting: boolean;
    profile: LegacyRecoveryProfile;
    onCancel: () => void;
    onConfirm: () => void;
};

export function LegacyRecoveryConfirmation({
    isSubmitting,
    profile,
    onCancel,
    onConfirm,
}: RecoveryConfirmationProps) {
    return (
        <div className="mt-6">
            <h2 className="font-serif text-xl font-bold text-stone-100">
                Recover “{profile.display_name}”?
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
                This will connect your account to this existing profile and restore
                access to its groups and planning data.
            </p>
            <div className="mt-4 rounded-md border border-slate-700 bg-[#141c26]/70 px-3 py-2">
                <p className="font-bold text-stone-100">{profile.display_name}</p>
                <p className="mt-1 text-xs text-slate-400">
                    {recoveryGroupSummary(profile)}
                </p>
            </div>
            <div className="mt-6 flex gap-3">
                <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={onCancel}
                    className="flex-1 rounded-md border border-slate-600 px-4 py-2.5 text-xs font-bold text-slate-200 transition hover:border-slate-500 disabled:opacity-60"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={onConfirm}
                    className="flex-1 rounded-md bg-[#d5a75b] px-4 py-2.5 text-xs font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:opacity-60"
                >
                    {isSubmitting ? "Recovering…" : "Recover profile"}
                </button>
            </div>
        </div>
    );
}
