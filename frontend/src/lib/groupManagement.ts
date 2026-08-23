import type { GroupRole } from "@/services/api";

export interface MemberManagementActions {
    canRemove: boolean;
    canPromote: boolean;
    canDemote: boolean;
}

export function memberManagementActions(
    currentRole: GroupRole,
    memberRole: GroupRole,
    isCurrentUser: boolean
): MemberManagementActions {
    if (isCurrentUser || memberRole === "owner") {
        return { canRemove: false, canPromote: false, canDemote: false };
    }

    if (currentRole === "owner") {
        return {
            canRemove: true,
            canPromote: memberRole === "member",
            canDemote: memberRole === "organizer",
        };
    }

    if (currentRole === "organizer" && memberRole === "member") {
        return { canRemove: true, canPromote: false, canDemote: false };
    }

    return { canRemove: false, canPromote: false, canDemote: false };
}

export function canLeaveGroup(currentRole: GroupRole): boolean {
    return currentRole !== "owner";
}
