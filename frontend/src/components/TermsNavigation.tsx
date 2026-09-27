"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { safeOnboardingNext, TERMS_REQUIRED_EVENT } from "@/lib/onboarding";

/** Route stale tabs through Next navigation when an API reports changed Terms. */
export default function TermsNavigation() {
    const router = useRouter();
    useEffect(() => {
        const handleTermsRequired = () => {
            if (window.location.pathname === "/onboarding") return;
            const next = safeOnboardingNext(window.location.pathname + window.location.search + window.location.hash);
            router.replace("/onboarding?next=" + encodeURIComponent(next));
        };
        window.addEventListener(TERMS_REQUIRED_EVENT, handleTermsRequired);
        return () => window.removeEventListener(TERMS_REQUIRED_EVENT, handleTermsRequired);
    }, [router]);
    return null;
}
