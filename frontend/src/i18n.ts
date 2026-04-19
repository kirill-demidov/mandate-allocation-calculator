import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";

const STORAGE_KEY = "ecalc_lang";

function initialLanguage(): string {
  if (typeof window === "undefined") return "ru";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "en" || stored === "ru") return stored;
  const nav = window.navigator.language || "";
  return nav.toLowerCase().startsWith("ru") ? "ru" : "en";
}

void i18n
  .use(initReactI18next)
  .init(
    {
      resources: {
        ru: { translation: ru },
        en: { translation: en },
      },
      lng: initialLanguage(),
      fallbackLng: "en",
      interpolation: { escapeValue: false },
    },
    () => {
      document.documentElement.lang = i18n.language;
    },
  );

export function setLanguage(lng: "ru" | "en") {
  void i18n.changeLanguage(lng);
  window.localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
}

export default i18n;
