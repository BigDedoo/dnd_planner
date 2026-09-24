import type { AvailabilityMode } from "@/services/api";

export const availabilityModeChoices: { value: AvailabilityMode; label: string }[] = [
    { value: "global", label: "🌐 Global" },
    { value: "separate", label: "👥 This group only" },
];

export function availabilityModeConfirmation(groupName: string): string {
    return `Use availability for ${groupName} only?\n\nYour current Global availability will be copied to this group. Future changes will be independent.`;
}

export function availabilitySaveFeedback(day: string, mode: AvailabilityMode, groupName: string): string {
    return mode === "global"
        ? `Availability saved for ${day} · shared with your Global groups.`
        : `Availability saved for ${day} · ${groupName} only.`;
}

export async function confirmedAvailabilityModeChange(
    mode: AvailabilityMode,
    groupName: string,
    separateAvailabilityInitialized: boolean,
    confirm: (message: string) => boolean,
    update: (mode: AvailabilityMode) => Promise<AvailabilityMode>
): Promise<AvailabilityMode | null> {
    if (mode === "separate" && !separateAvailabilityInitialized && !confirm(availabilityModeConfirmation(groupName))) return null;
    return update(mode);
}
