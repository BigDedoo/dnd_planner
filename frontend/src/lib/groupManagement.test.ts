import { describe, expect, it } from "vitest";

import { canLeaveGroup, memberManagementActions } from "./groupManagement";

describe("group member management UI permissions", () => {
    it("lets an owner manage members and organizers but never the owner", () => {
        expect(memberManagementActions("owner", "member", false)).toEqual({
            canRemove: true,
            canPromote: true,
            canDemote: false,
        });
        expect(memberManagementActions("owner", "organizer", false)).toEqual({
            canRemove: true,
            canPromote: false,
            canDemote: true,
        });
        expect(memberManagementActions("owner", "owner", false)).toEqual({
            canRemove: false,
            canPromote: false,
            canDemote: false,
        });
    });

    it("limits organizers to removing another ordinary member", () => {
        expect(memberManagementActions("organizer", "member", false)).toEqual({
            canRemove: true,
            canPromote: false,
            canDemote: false,
        });
        expect(memberManagementActions("organizer", "organizer", false).canRemove).toBe(false);
        expect(memberManagementActions("member", "member", false).canRemove).toBe(false);
    });

    it("does not expose self-management controls and keeps owners from leaving", () => {
        expect(memberManagementActions("owner", "member", true)).toEqual({
            canRemove: false,
            canPromote: false,
            canDemote: false,
        });
        expect(canLeaveGroup("owner")).toBe(false);
        expect(canLeaveGroup("organizer")).toBe(true);
        expect(canLeaveGroup("member")).toBe(true);
    });
});
