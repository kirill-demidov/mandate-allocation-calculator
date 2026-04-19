import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { CalculatorPrefillState } from "../types/calculatorPrefill";
import type {
  CleaElectionRow,
  ReferenceCountry,
  ReferenceElectionDetail,
  ReferenceElectionRow,
} from "../api/types";
import {
  cleaDuckdbDownloadHref,
  fetchCleaDetail,
  fetchCleaElections,
  fetchCleaPrefill,
  fetchReferenceCountries,
  fetchReferenceElectionDetail,
  fetchReferenceElections,
  fetchReferencePrefill,
  fetchReferenceStatus,
  postReferenceRefresh,
} from "../api/client";

const PAGE = 40;

function parlgovLoaded(s: Record<string, unknown> | null): boolean {
  const pg = s?.parlgov as Record<string, unknown> | undefined;
  return Boolean(pg?.loaded);
}

function cleaEnabled(s: Record<string, unknown> | null): boolean {
  const c = s?.clea as Record<string, unknown> | undefined;
  return Boolean(c?.enabled);
}

export function Reference() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [countries, setCountries] = useState<ReferenceCountry[]>([]);
  const [countryId, setCountryId] = useState<number | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [elections, setElections] = useState<ReferenceElectionRow[]>([]);
  const [electionTotal, setElectionTotal] = useState(0);
  const [cleaElections, setCleaElections] = useState<CleaElectionRow[]>([]);
  const [cleaTotal, setCleaTotal] = useState(0);
  const [detail, setDetail] = useState<ReferenceElectionDetail | null>(null);
  const [threshold, setThreshold] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listBusy, setListBusy] = useState(false);
  const [cleaListBusy, setCleaListBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [prefillBusy, setPrefillBusy] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canLoadMore = useMemo(
    () => elections.length < electionTotal,
    [elections.length, electionTotal],
  );

  const canLoadMoreClea = useMemo(
    () => cleaElections.length < cleaTotal,
    [cleaElections.length, cleaTotal],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchReferenceStatus();
      setStatus(s);
      const pg = s.parlgov as Record<string, unknown> | undefined;
      if (pg?.error) setError(String(pg.error));
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
    async (nextOffset: number, append: boolean) => {
      setListBusy(true);
      setError(null);
      try {
        const res = await fetchReferenceElections({
          countryId: typeof countryId === "number" ? countryId : undefined,
          limit: PAGE,
          offset: nextOffset,
          dateFrom: dateFrom.trim() || undefined,
          dateTo: dateTo.trim() || undefined,
          q: searchQ.trim() || undefined,
        });
        setElectionTotal(res.total);
        setElections((prev) => (append ? [...prev, ...res.items] : res.items));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setListBusy(false);
      }
    },
    [countryId, dateFrom, dateTo, searchQ],
  );

  const loadCleaElections = useCallback(
    async (nextOffset: number, append: boolean) => {
      setCleaListBusy(true);
      setError(null);
      try {
        const res = await fetchCleaElections({
          limit: PAGE,
          offset: nextOffset,
          dateFrom: dateFrom.trim() || undefined,
          dateTo: dateTo.trim() || undefined,
          q: searchQ.trim() || undefined,
        });
        setCleaTotal(res.total);
        setCleaElections((prev) => (append ? [...prev, ...res.items] : res.items));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setCleaListBusy(false);
      }
    },
    [dateFrom, dateTo, searchQ],
  );

  const formatRefreshPart = useCallback(
    (source: string, m: Record<string, unknown> | undefined) => {
      if (!m) return t("ref.refreshUnknown", { source });
      if (m.error)
        return t("ref.refreshSourceErr", { source, msg: String(m.error) });
      if (m.updated) return t("ref.refreshSourceUpdated", { source });
      if (m.reason === "no_csv")
        return t("ref.refreshSourceNoCsv", { source });
      if (m.skipped)
        return t("ref.refreshSourceSkip", {
          source,
          msg: String(m.message ?? m.reason ?? ""),
        });
      return t("ref.refreshUnknown", { source });
    },
    [t],
  );

  const onRefreshSources = useCallback(
    async (force: boolean) => {
      setRefreshBusy(true);
      setRefreshMsg(null);
      setError(null);
      try {
        const r = await postReferenceRefresh(force);
        const pg = r.parlgov as Record<string, unknown> | undefined;
        const cl = r.clea as Record<string, unknown> | undefined;
        setRefreshMsg(
          `${formatRefreshPart("ParlGov", pg)} ${formatRefreshPart("CLEA", cl)}`.trim(),
        );
        if (r.status) setStatus(r.status as Record<string, unknown>);
        const pgst = r.status?.parlgov as Record<string, unknown> | undefined;
        if (pgst?.error) setError(String(pgst.error));
        setDetail(null);
        setElections([]);
        setCleaElections([]);
        void loadElections(0, false);
        void loadCleaElections(0, false);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRefreshBusy(false);
      }
    },
    [formatRefreshPart, loadElections, loadCleaElections],
  );

  useEffect(() => {
    if (!parlgovLoaded(status)) return;
    setElections([]);
    setDetail(null);
    void loadElections(0, false);
  }, [status, countryId, dateFrom, dateTo, searchQ, loadElections]);

  useEffect(() => {
    if (!cleaEnabled(status)) return;
    setCleaElections([]);
    void loadCleaElections(0, false);
  }, [status, dateFrom, dateTo, searchQ, loadCleaElections]);

  async function onPickElection(id: number) {
    setDetailBusy(true);
    setError(null);
    try {
      const d = await fetchReferenceElectionDetail(id);
      setDetail({ ...d, source: "parlgov" });
      setThreshold(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDetail(null);
    } finally {
      setDetailBusy(false);
    }
  }

  async function onPickCleaElection(key: string) {
    setDetailBusy(true);
    setError(null);
    try {
      const d = await fetchCleaDetail(key);
      setDetail(d);
      setThreshold(
        typeof d.threshold_from_data === "number" ? d.threshold_from_data : 0,
      );
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
      let p;
      if (detail.source === "clea" && detail.election_key) {
        p = await fetchCleaPrefill(detail.election_key, threshold);
      } else if (detail.election_id != null) {
        p = await fetchReferencePrefill(detail.election_id, threshold);
      } else {
        throw new Error("no_election");
      }
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

  const seatsColLabel =
    detail?.source === "clea" ? t("ref.colSeatsClea") : t("ref.colSeatsParlgov");

  const detailSplit = useMemo(() => {
    if (!detail?.parties?.length) return null;
    let sumOfficial = 0;
    for (const p of detail.parties) {
      const v = p.vote_share;
      if (v != null && Number.isFinite(v) && v >= 0) sumOfficial += v;
    }
    const rows = detail.parties.map((p) => {
      const v = p.vote_share;
      const renorm =
        v != null && Number.isFinite(v) && v >= 0 && sumOfficial > 0
          ? (100 * v) / sumOfficial
          : null;
      return { party: p, renorm };
    });
    let sumSeats = 0;
    let seatsCounted = 0;
    let sumVotesEst = 0;
    let votesCounted = 0;
    for (const p of detail.parties) {
      if (p.seats_recorded != null && Number.isFinite(p.seats_recorded)) {
        sumSeats += p.seats_recorded;
        seatsCounted += 1;
      }
      if (p.votes_estimated != null && Number.isFinite(p.votes_estimated)) {
        sumVotesEst += p.votes_estimated;
        votesCounted += 1;
      }
    }
    return {
      rows,
      sumOfficial,
      sumSeats,
      seatsCounted,
      sumVotesEst,
      votesCounted,
    };
  }, [detail]);

  return (
    <article className="page-reference">
      <h1>{t("ref.title")}</h1>
      <p className="lead">{t("ref.lead")}</p>
      <p className="muted">{t("ref.attrib")}</p>

      {loading ? <p className="muted">{t("ref.loading")}</p> : null}
      {error ? <div className="error">{error}</div> : null}

      {!loading ? (
        <section className="panel">
          <h2 className="panel-title">{t("ref.refreshTitle")}</h2>
          <p className="muted">{t("ref.refreshLead")}</p>
          {refreshMsg ? <p className="muted">{refreshMsg}</p> : null}
          <p className="row-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={refreshBusy}
              onClick={() => void onRefreshSources(false)}
            >
              {t("ref.refreshCheck")}
            </button>
            <button
              type="button"
              className="btn"
              disabled={refreshBusy}
              onClick={() => void onRefreshSources(true)}
            >
              {t("ref.refreshForce")}
            </button>
          </p>
        </section>
      ) : null}

      {status && !parlgovLoaded(status) ? (
        <div className="panel">
          <p className="muted">{t("ref.unavailable")}</p>
        </div>
      ) : null}

      {!loading && parlgovLoaded(status) ? (
        <>
          <section className="panel">
            <h2 className="panel-title">{t("ref.filtersTitle")}</h2>
            <div className="grid-2" style={{ maxWidth: "42rem" }}>
              <label className="field">
                <span>{t("ref.country")}</span>
                <select
                  value={countryId === "" ? "" : String(countryId)}
                  onChange={(e) => {
                    const v = e.target.value;
                    setCountryId(v ? Number(v) : "");
                  }}
                >
                  <option value="">{t("ref.allCountries")}</option>
                  {countries.map((c) => (
                    <option key={c.country_id} value={c.country_id}>
                      {c.code} — {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>{t("ref.searchCountry")}</span>
                <input
                  type="search"
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  placeholder={t("ref.searchCountryPh")}
                />
              </label>
              <label className="field">
                <span>{t("ref.dateFrom")}</span>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                />
              </label>
              <label className="field">
                <span>{t("ref.dateTo")}</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                />
              </label>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">{t("ref.electionsTitle")}</h2>
            {listBusy && !elections.length ? (
              <p className="muted">{t("ref.loadingList")}</p>
            ) : null}
            <div className="table-wrap">
              <table className="data table-ref-pick">
                <colgroup>
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "14%" }} />
                  <col style={{ width: "34%" }} />
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "12%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th className="num">{t("ref.colId")}</th>
                    <th>{t("ref.colDate")}</th>
                    <th>{t("ref.colCountry")}</th>
                    <th className="num">{t("ref.colSeats")}</th>
                    <th className="num">{t("ref.colSeatsPr")}</th>
                    <th className="num">{t("ref.colSeatsSmd")}</th>
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
                      <td className="num">—</td>
                      <td className="num">—</td>
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
            <p className="muted">{t("ref.parlgovSeatsTierFoot")}</p>
            {canLoadMore ? (
              <p className="row-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={listBusy}
                  onClick={() => void loadElections(elections.length, true)}
                >
                  {t("ref.loadMore")}
                </button>
              </p>
            ) : null}
          </section>

          {cleaEnabled(status) ? (
            <section className="panel">
              <h2 className="panel-title">{t("ref.cleaTitle")}</h2>
              <p className="muted">{t("ref.cleaLead")}</p>
              <p className="row-actions">
                <a className="btn btn-secondary" href={cleaDuckdbDownloadHref()} download>
                  {t("ref.cleaDownloadDuckdb")}
                </a>
              </p>
              {cleaListBusy && !cleaElections.length ? (
                <p className="muted">{t("ref.loadingList")}</p>
              ) : null}
              <div className="table-wrap">
                <table className="data table-ref-pick">
                  <colgroup>
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "10%" }} />
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "10%" }} />
                    <col style={{ width: "8%" }} />
                    <col style={{ width: "8%" }} />
                    <col style={{ width: "8%" }} />
                    <col style={{ width: "8%" }} />
                    <col style={{ width: "12%" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>{t("ref.cleaColKey")}</th>
                      <th>{t("ref.colDate")}</th>
                      <th>{t("ref.colCountry")}</th>
                      <th className="num">{t("ref.cleaColVotes")}</th>
                      <th className="num">{t("ref.colSeats")}</th>
                      <th className="num">{t("ref.colSeatsPr")}</th>
                      <th className="num">{t("ref.colSeatsSmd")}</th>
                      <th className="num">{t("ref.cleaColThr")}</th>
                      <th>{t("ref.colOpen")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cleaElections.map((row) => (
                      <tr key={row.election_key}>
                        <td className="muted">{row.election_key}</td>
                        <td>{row.election_date}</td>
                        <td>{row.country_label ?? "—"}</td>
                        <td className="num">{row.votes_valid ?? "—"}</td>
                        <td className="num">{row.seats_total ?? "—"}</td>
                        <td className="num">{row.seats_pr_tier ?? "—"}</td>
                        <td className="num">{row.seats_constituency_tier ?? "—"}</td>
                        <td className="num">
                          {row.threshold_percent != null
                            ? `${row.threshold_percent}%`
                            : "—"}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => void onPickCleaElection(row.election_key)}
                          >
                            {t("ref.choose")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {canLoadMoreClea ? (
                <p className="row-actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={cleaListBusy}
                    onClick={() => void loadCleaElections(cleaElections.length, true)}
                  >
                    {t("ref.loadMore")}
                  </button>
                </p>
              ) : null}
            </section>
          ) : status && !(status.clea as { enabled?: boolean })?.enabled ? (
            <section className="panel">
              <h2 className="panel-title">{t("ref.cleaTitle")}</h2>
              <p className="muted">{t("ref.cleaDisabled")}</p>
            </section>
          ) : null}

          {detailBusy ? <p className="muted">{t("ref.loadingDetail")}</p> : null}

          {detail ? (
            <section className="panel">
              <h2 className="panel-title">{t("ref.detailTitle")}</h2>
              <p className="muted">
                {detail.source === "clea"
                  ? `${detail.country_name ?? "—"} · ${detail.election_date ?? "—"}`
                  : `${detail.country_code ?? "—"} · ${detail.election_date ?? "—"}`}{" "}
                · {t("ref.seatsTotal", { n: detail.seats_total ?? "—" })}
                {detail.votes_valid != null
                  ? ` · ${t("ref.votesValid", { n: detail.votes_valid })}`
                  : null}
                {detail.source === "clea" ? ` · ${t("ref.sourceClea")}` : null}
              </p>
              <p className="muted">
                {detail.source === "clea" &&
                detail.seats_pr_tier != null &&
                detail.seats_constituency_tier != null
                  ? t("ref.seatsTierCleaSplit", {
                      pr: detail.seats_pr_tier,
                      co: detail.seats_constituency_tier,
                      tot: detail.seats_total ?? "—",
                    })
                  : detail.source === "clea"
                    ? t("ref.seatsTierCleaNoMag")
                    : t("ref.seatsTierParlgov")}
              </p>
              <p className="muted">
                {detail.source === "clea" && detail.threshold_from_data != null
                  ? t("ref.thresholdHintClea", {
                      n: detail.threshold_from_data,
                    })
                  : t("ref.thresholdHint")}
              </p>
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

              <h3 className="ref-detail-split-title">{t("ref.detailSplitTitle")}</h3>
              <p className="muted ref-detail-split-lead">{t("ref.detailSplitLead")}</p>

              <div className="table-wrap">
                <table className="data table-ref-detail">
                  <colgroup>
                    <col style={{ width: "36%" }} />
                    <col style={{ width: "16%" }} />
                    <col style={{ width: "16%" }} />
                    <col style={{ width: "16%" }} />
                    <col style={{ width: "16%" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">{t("ref.colParty")}</th>
                      <th scope="col" className="num">
                        {t("ref.colShareOfficial")}
                      </th>
                      <th scope="col" className="num">
                        {t("ref.colShareRenorm")}
                      </th>
                      <th scope="col" className="num">
                        {seatsColLabel}
                      </th>
                      <th scope="col" className="num">
                        {t("ref.colVotesEst")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detailSplit?.rows ?? []).map(({ party: p, renorm }) => (
                      <tr key={p.name}>
                        <td className="party-cell">{p.name}</td>
                        <td className="num">
                          {p.vote_share != null ? `${p.vote_share.toFixed(2)}%` : "—"}
                        </td>
                        <td className="num">
                          {renorm != null ? `${renorm.toFixed(2)}%` : "—"}
                        </td>
                        <td className="num">{p.seats_recorded ?? "—"}</td>
                        <td className="num">{p.votes_estimated ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                  {detailSplit && detailSplit.sumOfficial > 0 ? (
                    <tfoot>
                      <tr className="ref-detail-tfoot">
                        <th scope="row">{t("ref.rowTotal")}</th>
                        <td className="num">{detailSplit.sumOfficial.toFixed(2)}%</td>
                        <td className="num">100.00%</td>
                        <td className="num">
                          {detailSplit.seatsCounted > 0 ? detailSplit.sumSeats : "—"}
                        </td>
                        <td className="num">
                          {detailSplit.votesCounted > 0 ? detailSplit.sumVotesEst : "—"}
                        </td>
                      </tr>
                    </tfoot>
                  ) : null}
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
