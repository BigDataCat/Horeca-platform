import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ro } from "./locales/ro";

export type Lang = "en" | "ro";
const KEY = "horeca_lang";

type Ctx = { lang: Lang; setLang: (lang: Lang) => void };
const I18nContext = createContext<Ctx>({ lang: "en", setLang: () => {} });

function initialLang(): Lang {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "en" || stored === "ro") return stored;
  } catch {
    /* storage unavailable */
  }
  return navigator.language?.toLowerCase().startsWith("ro") ? "ro" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = next;
  }, []);
  const value = useMemo(() => ({ lang, setLang }), [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export const useLang = () => useContext(I18nContext);

/** `t("English text")` returns the Romanian translation when the language is "ro"; English text is the
 * key, so a missing translation simply stays in English. */
export function useT() {
  const { lang } = useContext(I18nContext);
  return useCallback((text: string) => (lang === "ro" ? ro[text] ?? text : text), [lang]);
}

export function LanguageSwitch() {
  const { lang, setLang } = useLang();
  return (
    <div className="lang-switch" role="group" aria-label="Language">
      {(["en", "ro"] as Lang[]).map((code) => (
        <button key={code} type="button" className={lang === code ? "active" : "secondary"} onClick={() => setLang(code)} aria-pressed={lang === code}>
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
