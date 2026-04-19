import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AUTHOR_GITHUB_URL,
  AUTHOR_NAME,
  AUTHOR_NAME_RU,
  CONTACT_EMAIL,
} from "../siteMeta";

export function Landing() {
  const { t, i18n } = useTranslation();
  const ru = i18n.language === "ru";
  return (
    <article>
      <h1>{t("landing.title")}</h1>
      <p className="lead">{t("landing.lead")}</p>
      <p className="muted landing-author">
        {t("landingAuthorIntro")}{" "}
        <strong>{ru ? AUTHOR_NAME_RU : AUTHOR_NAME}</strong>
        {" · "}
        <a href={AUTHOR_GITHUB_URL} target="_blank" rel="noopener noreferrer">
          {t("landingAuthorGithub")}
        </a>
        {" · "}
        {t("landingAuthorContact")}{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
      </p>

      <h2>{t("landing.whatTitle")}</h2>
      <p>{t("landing.whatP1")}</p>
      <p>{t("landing.whatP2")}</p>

      <h2>{t("landing.whoTitle")}</h2>
      <p>{t("landing.whoP")}</p>

      <h2>{t("landing.methodsTitle")}</h2>
      <p>{t("landing.methodsList")}</p>

      <h2>{t("landing.refTitle")}</h2>
      <p>{t("landing.refP1")}</p>
      <p>{t("landing.refP2")}</p>

      <p className="landing-actions">
        <Link className="btn btn-primary" to="/app">
          {t("landing.cta")}
        </Link>
        <Link className="btn" to="/app/votes">
          {t("landing.ctaVotes")}
        </Link>
        <Link className="btn btn-secondary" to="/reference">
          {t("landing.ctaRef")}
        </Link>
      </p>
    </article>
  );
}
