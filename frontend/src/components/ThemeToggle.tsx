"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "./ThemeProvider";

export function ThemeToggle() {
    const { toggleTheme } = useTheme();

    return (
        <button
            onClick={toggleTheme}
            className="rounded-md border border-slate-700 bg-slate-800/80 p-1.5 text-slate-300 transition-colors hover:border-amber-300/50 hover:bg-slate-700 hover:text-amber-100"
            aria-label="Toggle dark mode"
        >
            <Moon size={20} className="block dark:hidden" />
            <Sun size={20} className="hidden dark:block" />
        </button>
    );
}
