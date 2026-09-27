// Server-only runtime configuration: import only from dynamic server pages.
import { supportContactUrl } from "./supportContact";

export function legalDetails() {
    const text = (key: string) => process.env[key]?.trim() || null;
    return {
        operatorName: text("LEGAL_OPERATOR_NAME"), operatorStatus: text("LEGAL_OPERATOR_STATUS"),
        operatorAddress: text("LEGAL_OPERATOR_ADDRESS"), operatorPhone: text("LEGAL_OPERATOR_PHONE"),
        operatorContact: supportContactUrl(process.env.LEGAL_OPERATOR_CONTACT) || supportContactUrl(process.env.SUPPORT_CONTACT_URL),
        publicationDirector: text("LEGAL_PUBLICATION_DIRECTOR"),
    };
}
