import { formatInviteCodeInput } from "./inviteCode";

export function directInvitePath(code: string): string {
    return `/join/${encodeURIComponent(formatInviteCodeInput(code))}`;
}
