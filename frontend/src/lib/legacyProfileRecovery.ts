import type { LegacyRecoveryProfile, OnboardingStatus } from "../services/api";

export type RecoveryOnboardingMode = "choice" | "create" | "recover";

export function initialRecoveryMode(
    profiles: LegacyRecoveryProfile[]
): RecoveryOnboardingMode {
    return profiles.length > 0 ? "choice" : "create";
}

export function recoveryGroupSummary(profile: LegacyRecoveryProfile): string {
    return profile.group_names.length > 0
        ? profile.group_names.join(" · ")
        : "No groups listed";
}

export async function claimOrRefreshOnConflict(
    userId: string,
    claim: (userId: string) => Promise<OnboardingStatus>,
    refresh: () => Promise<LegacyRecoveryProfile[]>,
): Promise<
    | { status: "claimed"; onboarding: OnboardingStatus }
    | { status: "conflict"; profiles: LegacyRecoveryProfile[] }
> {
    try {
        return { status: "claimed", onboarding: await claim(userId) };
    } catch (error) {
        if (error instanceof Error && error.name === "LegacyRecoveryConflictError") {
            return { status: "conflict", profiles: await refresh() };
        }
        throw error;
    }
}
