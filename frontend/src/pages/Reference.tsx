import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { CalculatorPrefillState } from "../types/calculatorPrefill";
import type {
  ReferenceCountry,
  ReferenceElectionDetail,
  ReferenceElectionRow,
} from "../api/types";
import {
  fetchReferenceCountries,
  fetchReferenceElectionDetail,
  fetchReferenceElections,
  fetchReferencePrefill,
  fetchReferenceStatus,
} from "../api/client";

const PAGE = 40;

export function Reference() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [countries, setCountries] = useState<ReferenceCountry[]>([]);
  const [countryId, setCountryId] = useState<number | "">("");
  const [elections, setElections] = useState<ReferenceElectionRow[]>([]);
  const [electionTotal, setElectionTotal] = useState(0);
  const [detail, setDetail] = useState<ReferenceElectionDetail | null>(null);
  const [threshold, setThreshold] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listBusy, setListBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [prefillBusy, setPrefillBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canLoadMore = useMemo(
    () => typeof countryId === "number" && elections.length < electionTotal,
    [countryId, elections.length, electionTotal],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchReferenceStatus();
      setStatus(s);
      if (s.error) setError(String(s.error));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await refreshStatus();
        const list = await fetchReferenceCountries();
        if (cancelled) return;
        setCountries(list);
        if (list.length && countryId === "") {
          setCountryId(list[0].country_id);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  const loadElections = useCallback(
    async (cid: number, nextOffset: number, append: boolean) => {
      setListBusy(true);
      setError(null);
      try {
        const res = await fetchReferenceElections(cid, PAGE, nextOffset);
        setElectionTotal(res.total);
        setElections((prev) => (append ? [...prev, ...res.items] : res.items));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setListBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (typeof countryId !== "number") return;
    setElections([]);
    setDetail(null);
    void loadElections(countryId, 0, false);
  }, [countryId, loadElections]);

  async function onPickElection(id: number) {
    setDetailBusy(true);
    setError(null);
    try {
      const d = await fetchReferenceElectionDetail(id);
      setDetail(d);
      setThreshold(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDetail(null);
    } finally {
      setDetailBusy(false);
    }
  }

  async function onOpenCalculator() {
    if (!detail) return;
    setPrefillBusy(true);
    setError(null);
    try {
      const p = await fetchReferencePrefill(detail.election_id, threshold);
      const state: CalculatorPrefillState = {
        totalMandates: p.totalMandates,
        thresholdPercent: p.thresholdPercent,
        parties: p.parties,
      };
      navigate("/app", { state });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPrefillBusy(false);
    }
  }

  return (
    <article className="page-reference">
      <h1>{t("ref.title")}</h1>
      <p className="lead">{t("ref.lead")}</p>
      <p className="muted">{t("ref.attrib")}</p>

      {loading ? <p className="muted">{t("ref.loading")}</p> : null}
      {error ? <div className="error">{error}</div> : null}

      {status && !status.loaded ? (
        <div className="panel">
          <p className="muted">{t("ref.unavailable")}</p>
        </div>
      ) : null}

      {!loading && status?.loaded ? (
        <>
          <section className="panel">
            <h2 className="panel-title">{t("ref.pickCountry")}</h2>
            <label className="field" style={{ maxWidth: "28rem" }}>
              <span>{t("ref.country")}</span>
              <select
                value={countryId === "" ? "" : String(countryId)}
                onChange={(e) => {
                  const v = e.target.value;
                  setCountryId(v ? Number(v) : "");
                }}
              >
                {countries.map((c) => (
                  <option key={c.country_id} value={c.country_id}>
                    {c.code} — {c.name}
                  </option>
                ))}
              </select>
            </label>
          </section>

          <section className="panel">
            <h2 className="panel-title">{t("ref.electionsTitle")}</h2>
            {listBusy && !elections.length ? (
              <p className="muted">{t("ref.loadingList")}</p>
            ) : null}
            <div className="table-wrap">
              <table className="data table-ref-pick">
                <colgroup>
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "16%" }} />
                  <col style={{ width: "44%" }} />
                  <col style={{ width: "14%" }} />
                  <col style={{ width: "14%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th className="num">{t("ref.colId")}</th>
                    <th>{t("ref.colDate")}</th>
                    <th>{t("ref.colCountry")}</th>
                    <th className="num">{t("ref.colSeats")}</th>
                    <th>{t("ref.colOpen")}</th>
                  </tr>
                </thead>
                <tbody>
                  {elections.map((row) => (
                    <tr key={row.election_id}>
                      <td className="num">{row.election_id}</td>
                      <td>{row.election_date}</td>
                      <td>
                        {row.country_code} — {row.country_name}
                      </td>
                      <td className="num">{row.seats_total ?? "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => void onPickElection(row.election_id)}
                        >
                          {t("ref.choose")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canLoadMore ? (
              <p className="row-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={listBusy || typeof countryId !== "number"}
                  onClick={() =>
                    typeof countryId === "number" &&
                    void loadElections(countryId, elections.length, true)
                  }
                >
                  {t("ref.loadMore")}
                </button>
              </p>
            ) : null}
          </section>

          {detailBusy ? <p className="muted">{t("ref.loadingDetail")}</p> : null}

          {detail ? (
            <section className="panel">
              <h2 className="panel-title">{t("ref.detailTitle")}</h2>
              <p className="muted">
                {detail.country_code} · {detail.election_date} ·{" "}
                {t("ref.seatsTotal", { n: detail.seats_total ?? "—" })}
                {detail.votes_valid != null
                  ? ` · ${t("ref.votesValid", { n: detail.votes_valid })}`
                  : null}
              </p>
              <p className="muted">{t("ref.thresholdHint")}</p>
              <label className="field" style={{ maxWidth: "12rem" }}>
                <span>{t("ref.thresholdLabel")}</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                />
              </label>

              <div className="table-wrap">
                <table className="data table-ref-detail">
                  <colgroup>
                    <col style={{ width: "46%" }} />
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "18%" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">{t("ref.colParty")}</th>
                      <th scope="col" className="num">
                        {t("ref.colShare")}
                      </th>
                      <th scope="col" className="num">
                        {t("ref.colSeatsParlgov")}
                      </th>
                      <th scope="col" className="num">
                        {t("ref.colVotesEst")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.parties.map((p) => (
                      <tr key={p.name}>
                        <td className="party-cell">{p.name}</td>
                        <td className="num">
                          {p.vote_share != null ? `${p.vote_share.toFixed(2)}%` : "—"}
                        </td>
                        <td className="num">{p.seats_recorded ?? "—"}</td>
                        <td className="num">{p.votes_estimated ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="row-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={prefillBusy}
                  onClick={() => void onOpenCalculator()}
                >
                  {t("ref.openCalc")}
                </button>
                <Link className="btn btn-secondary" to="/app">
                  {t("ref.toCalcBlank")}
                </Link>
              </p>
            </section>
          ) : null}
        </>
      ) : null}

      <p className="muted" style={{ marginTop: "2rem" }}>
        <Link to="/">{t("nav.landing")}</Link>
      </p>
    </article>
  );
}
