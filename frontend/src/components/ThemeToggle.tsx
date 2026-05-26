"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { useTheme } from "./ThemeProvider";

export function ThemeToggle() {
    const { theme, toggleTheme } = useTheme();
    const mounted = useSyncExternalStore(
        () => () => undefined,
        () => true,
        () => false
    );

    if (!mounted) {
        return <div className="w-10 h-10" />; // placeholder
    }

    return (
        <button
            onClick={toggleTheme}
            className="p-2 rounded-full border border-gray-200 bg-white text-gray-800 hover:bg-gray-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 transition-colors shadow-sm"
            aria-label="Toggle dark mode"
        >
            {theme === "light" ? <Moon size={20} /> : <Sun size={20} />}
        </button>
    );
}
