export function formatInviteCodeInput(value: string): string {
    const characters = value
        .toUpperCase()
        .replace(/[^ABCDEFGHJKLMNPQRSTUVWXYZ23456789]/g, "")
        .slice(0, 8);
    return characters.length > 4
        ? `${characters.slice(0, 4)}-${characters.slice(4)}`
        : characters;
}
