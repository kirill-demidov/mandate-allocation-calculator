const GA_ID = import.meta.env.VITE_GA_MEASUREMENT_ID;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

const INIT_FLAG = "__electoralCalcGaInited";

/** Подключает gtag.js и очередь вызовов до загрузки скрипта (как в официальном сниппете GA4). */
export function initGoogleAnalytics(): void {
  if (!GA_ID || typeof window === "undefined") return;
  if ((window as unknown as Record<string, boolean>)[INIT_FLAG]) return;
  (window as unknown as Record<string, boolean>)[INIT_FLAG] = true;

  window.dataLayer = window.dataLayer ?? [];
  window.gtag = function gtag(...args: unknown[]) {
    window.dataLayer!.push(args);
  };

  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_ID)}`;
  document.head.appendChild(script);

  window.gtag("js", new Date());
  window.gtag("config", GA_ID, { send_page_view: false });
}

/** SPA: отправить просмотр страницы (после init). */
export function trackPageView(path: string): void {
  if (!GA_ID || !window.gtag) return;
  window.gtag("config", GA_ID, { page_path: path });
}
