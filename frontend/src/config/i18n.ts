import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import cs from "@/assets/locales/cs.json";

void i18n.use(initReactI18next).init({
  resources: {
    cs: { translation: cs },
  },
  lng: "cs", // default language
  fallbackLng: "cs",

  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
