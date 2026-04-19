import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";
import {
  AUTHOR_GITHUB_URL,
  AUTHOR_NAME,
  AUTHOR_NAME_RU,
  CONTACT_EMAIL,
} from "../siteMeta";

export function Shell() {
  const { t, i18n } = useTranslation();
  const lng = i18n.language === "en" ? "en" : "ru";

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-header-inner">
          <NavLink className="brand" to="/">
            {t("brand")}
          </NavLink>
          <nav className="nav">
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {t("nav.landing")}
            </NavLink>
            <NavLink
              to="/app"
              end
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {t("nav.app")}
            </NavLink>
            <NavLink
              to="/app/votes"
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {t("nav.votes")}
            </NavLink>
            <div className="lang-switch" role="group" aria-label="Language">
              <button
                type="button"
                className={lng === "ru" ? "active" : ""}
                onClick={() => setLanguage("ru")}
              >
                RU
              </button>
              <button
                type="button"
                className={lng === "en" ? "active" : ""}
                onClick={() => setLanguage("en")}
              >
                EN
              </button>
            </div>
          </nav>
        </div>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
      <footer className="shell-footer">
        <div className="shell-footer-inner">
          <p className="shell-footer-disclaimer">{t("footer")}</p>
          <p className="shell-footer-meta">
            <span className="shell-footer-meta-line">
              {t("footerAuthor")}{" "}
              <strong>{lng === "ru" ? AUTHOR_NAME_RU : AUTHOR_NAME}</strong>
              {" · "}
              <a href={AUTHOR_GITHUB_URL} target="_blank" rel="noopener noreferrer">
                {t("footerGithub")}
              </a>
            </span>
            <span className="shell-footer-meta-line">
              {t("footerContactIntro")}{" "}
              <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
            </span>
          </p>
        </div>
      </footer>
    </div>
  );
}
