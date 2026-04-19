import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { initGoogleAnalytics, trackPageView } from "../analytics";

/** Отправляет page_view в GA4 при смене маршрута (и при первом заходе). */
export function GoogleAnalyticsListener() {
  const location = useLocation();

  useEffect(() => {
    initGoogleAnalytics();
  }, []);

  useEffect(() => {
    trackPageView(location.pathname + location.search);
  }, [location.pathname, location.search]);

  return null;
}
