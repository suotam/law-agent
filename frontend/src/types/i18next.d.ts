import "i18next";
import cs from "@/assets/locales/cs.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: {
      translation: typeof cs;
    };
    returnNull: false;
  }
}
