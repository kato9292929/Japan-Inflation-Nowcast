"use client";

// JP/EN トグルの状態を Wire から子に配る。Wire の外では "en"（SSR と同じ既定）。
import { createContext, useContext } from "react";

export type Lang = "en" | "ja";

export const LangContext = createContext<Lang>("en");

export function useLang(): Lang {
  return useContext(LangContext);
}
