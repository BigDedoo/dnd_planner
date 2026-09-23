import { format } from "date-fns";

export function inviteUseCountLabel(useCount: number): string {
    if (useCount === 0) return "No one has joined with this invite yet.";
    return `Used ${useCount} ${useCount === 1 ? "time" : "times"}`;
}

export function inviteCreatedLabel(createdAt: string): string {
    return `Created ${format(new Date(createdAt), "MMM d")}`;
}

export function confirmInviteChange(
    action: "replace" | "revoke",
    confirm: (message: string) => boolean
): boolean {
    return confirm(action === "replace"
        ? "Creating a new invite will immediately invalidate the current invite link. Replace invite?"
        : "Revoke this invite? Anyone using this link will no longer be able to join.");
}

export async function confirmedInviteMutation<T>(
    action: "replace" | "revoke",
    confirm: (message: string) => boolean,
    mutate: () => Promise<T>
): Promise<T | null> {
    if (!confirmInviteChange(action, confirm)) return null;
    return mutate();
}

export async function copyInviteText(
    value: string,
    clipboard: Pick<Clipboard, "writeText"> | undefined
): Promise<void> {
    if (!clipboard?.writeText) throw new Error("Clipboard is unavailable");
    await clipboard.writeText(value);
}

export async function shareInviteLink(
    url: string,
    groupName: string,
    share: (data: ShareData) => Promise<void>
): Promise<"shared" | "cancelled"> {
    try {
        await share({
            title: `Join ${groupName} on DnD Planner`,
            text: "Join our DnD group on DnD Planner.",
            url,
        });
        return "shared";
    } catch (error) {
        if (error && typeof error === "object" && "name" in error && error.name === "AbortError") {
            return "cancelled";
        }
        throw error;
    }
}
