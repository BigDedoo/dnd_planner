import { formatInviteCodeInput } from "./inviteCode";

export function directInvitePath(code: string): string {
    return `/join/${encodeURIComponent(formatInviteCodeInput(code))}`;
}

export function directInviteUrl(origin: string, code: string): string {
    return new URL(directInvitePath(code), origin).toString();
}

export function invitePreviewErrorCopy(message: string): { title: string; detail: string } {
    if (message === "Invite code is invalid or has been revoked") {
        return {
            title: "This invitation is no longer available.",
            detail: "It may have been revoked or replaced. Ask the group owner for a new link.",
        };
    }
    return { title: "Could not check this invitation.", detail: "Please try again, or ask the group owner for a new link." };
}

export async function joinAndOpenInvitedGroup<T extends { id: string }>(
    code: string,
    nickname: string | undefined,
    getToken: () => Promise<string | null>,
    join: (code: string, nickname: string | undefined, token: string | null) => Promise<T>,
    replace: (path: string) => void
): Promise<T> {
    const token = await getToken();
    const group = await join(code, nickname, token);
    replace(`/groups/${group.id}`);
    return group;
}
