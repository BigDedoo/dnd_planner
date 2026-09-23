import type { AvailabilityMode } from "@/services/api";

export function availabilityModeConfirmation(mode: AvailabilityMode, groupName: string): string {
    return mode === "separate"
        ? `Manage availability separately for ${groupName}?\n\nYour current global availability will be copied as a starting point the first time. Future changes here will not affect your other groups.`
        : `Use global availability for ${groupName}?\n\nYour separate responses will be kept but hidden while Global availability is active. They will be restored if you switch back.`;
}

export function availabilitySaveFeedback(day: string, mode: AvailabilityMode, groupName: string): string {
    return mode === "global"
        ? `Availability saved for ${day} · shared with your Global groups.`
        : `Availability saved for ${day} · ${groupName} only.`;
}

export async function confirmedAvailabilityModeChange(
    mode: AvailabilityMode,
    groupName: string,
    confirm: (message: string) => boolean,
    update: (mode: AvailabilityMode) => Promise<AvailabilityMode>
): Promise<AvailabilityMode | null> {
    if (!confirm(availabilityModeConfirmation(mode, groupName))) return null;
    return update(mode);
}
