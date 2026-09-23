import type { FormEventHandler } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, UsersRound } from "lucide-react";

import { invitePreviewErrorCopy } from "@/lib/directInvite";

export function InviteJoinForm({ groupName, nickname, joining, error, onNicknameChange, onSubmit }: {
    groupName: string;
    nickname: string;
    joining: boolean;
    error: string | null;
    onNicknameChange: (value: string) => void;
    onSubmit: FormEventHandler<HTMLFormElement>;
}) {
    return <form onSubmit={onSubmit} className="min-w-0">
        <div className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.05] p-4">
            <div className="flex items-center gap-2 text-emerald-200"><CheckCircle2 size={17} /><span className="text-xs font-bold uppercase tracking-[0.14em]">Invite verified</span></div>
            <p className="mt-2 break-words font-serif text-2xl font-bold text-stone-100">{groupName}</p>
        </div>
        <label className="mt-6 block text-xs font-bold text-slate-200">
            Your name in this group <span className="font-normal text-slate-500">(optional)</span>
            <input value={nickname} onChange={(event) => onNicknameChange(event.target.value)} maxLength={120} placeholder="Use your global display name" className="mt-1.5 w-full min-w-0 rounded-md border border-slate-600 bg-[#111820] px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-amber-200/70" />
        </label>
        <p className="mt-2 text-xs leading-5 text-slate-500">This nickname is only shown inside this group. You can change it later.</p>
        {error && <p role="alert" className="mt-4 break-words text-sm font-semibold text-rose-200">{error}</p>}
        <button type="submit" disabled={joining} className="mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md bg-[#d5a75b] px-4 py-2.5 text-sm font-bold text-[#18140f] transition hover:bg-[#e4bc77] disabled:cursor-not-allowed disabled:opacity-60">
            <UsersRound size={16} /> {joining ? "Joining group..." : "Join group"}
        </button>
    </form>;
}

export function InviteUnavailable({ message }: { message: string }) {
    const copy = invitePreviewErrorCopy(message);
    return <div>
        <div role="alert" className="rounded-xl border border-rose-300/20 bg-rose-300/[0.05] p-4">
            <p className="break-words font-semibold text-rose-200">{copy.title}</p>
            <p className="mt-1 break-words text-sm leading-6 text-slate-400">{copy.detail}</p>
        </div>
        <Link href="/app" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-amber-200 transition hover:text-amber-100">Go to dashboard <ArrowRight size={15} /></Link>
    </div>;
}
