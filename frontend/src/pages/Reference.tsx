import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { CalculatorPrefillState } from "../types/calculatorPrefill";
import type {
  CountrySummary,
  ReferenceCountry,
  ReferenceElectionDetail,
  UnifiedElectionRow,
} from "../api/types";
import {
  fetchCleaDetail,
  fetchCleaPrefill,
  fetchReferenceCountries,
  fetchReferenceElectionDetail,
  fetchReferencePrefill,
  fetchReferenceStatus,
  fetchSummaries,
  fetchUnifiedElections,
  postGenerateSummary,
  postReferenceRefresh,
  referenceDuckdbDownloadHref,
} from "../api/client";

const PAGE = 40;

type DetailSplit = {
  rows: { party: { name: string; vote_share: number | null; seats_recorded: number | null; votes_estimated: number | null }; renorm: number | null }[];
  sumOfficial: number;
  sumSeats: number;
  seatsCounted: number;
  sumVotesEst: number;
  votesCounted: number;
} | null;

function InlineDetail({
  detail,
  detailSplit,
  seatsColLabel,
  threshold,
  setThreshold,
  prefillBusy,
  onOpenCalculator,
  countrySummary,
  lang,
  onGenerateSummary,
  t,
}: {
  detail: ReferenceElectionDetail;
  detailSplit: DetailSplit;
  seatsColLabel: string;
  threshold: number;
  setThreshold: (v: number) => void;
  prefillBusy: boolean;
  onOpenCalculator: () => void;
  countrySummary: CountrySummary | null;
  lang: string;
  onGenerateSummary: (apiKey: string) => Promise<CountrySummary>;
  t: (k: string, opts?: Record<string, unknown>) => string;
}) {
  const [activeTab, setActiveTab] = useState<"parties" | "system">("parties");
  const [showModal, setShowModal] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [generateBusy, setGenerateBusy] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [localSummary, setLocalSummary] = useState<CountrySummary | null>(null);

  const currentSummary = localSummary ?? countrySummary;
  const apiKeyRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLocalSummary(null);
    setActiveTab("parties");
  }, [detail.election_date, detail.country_code]);

  useEffect(() => {
    if (showModal) setTimeout(() => apiKeyRef.current?.focus(), 50);
  }, [showModal]);

  async function handleGenerate() {
    if (!apiKey.trim()) return;
    setGenerateBusy(true);
    setGenerateError(null);
    try {
      const result = await onGenerateSummary(apiKey.trim());
      setLocalSummary(result);
      setShowModal(false);
      setApiKey("");
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerateBusy(false);
    }
  }

  const summaryText = currentSummary
    ? (lang === "ru" ? currentSummary.summary_ru : currentSummary.summary_en) || currentSummary.summary_en
    : null;

  return (
    <div className="ref-inline-detail">
      <p className="muted" style={{ marginBottom: "0.4rem" }}>
        {detail.source === "clea"
          ? `${detail.country_name ?? "—"} · ${detail.election_date ?? "—"}`
          : `${detail.country_code ?? "—"} · ${detail.election_date ?? "—"}`}
        {detail.seats_total != null ? ` · ${t("ref.seatsTotal", { n: detail.seats_total })}` : ""}
        {detail.votes_valid != null ? ` · ${t("ref.votesValid", { n: detail.votes_valid })}` : ""}
      </p>
      <p className="muted" style={{ marginBottom: "0.4rem" }}>
        {detail.source === "clea" && detail.seats_pr_tier != null && detail.seats_constituency_tier != null
          ? t("ref.seatsTierCleaSplit", { pr: detail.seats_pr_tier, co: detail.seats_constituency_tier, tot: detail.seats_total ?? "—" })
          : detail.source === "clea"
            ? t("ref.seatsTierCleaNoMag")
            : t("ref.seatsTierParlgov")}
      </p>

      {/* Tab switcher */}
      <div className="ref-tabs" style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
        <button
          type="button"
          className={`btn btn-sm${activeTab === "parties" ? " btn-active" : ""}`}
          onClick={() => setActiveTab("parties")}
        >
          {t("ref.tabParties")}
        </button>
        <button
          type="button"
          className={`btn btn-sm${activeTab === "system" ? " btn-active" : ""}`}
          onClick={() => setActiveTab("system")}
        >
          {t("ref.tabSystem")}
        </button>
      </div>

      {activeTab === "parties" ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
            <label className="field" style={{ maxWidth: "10rem", margin: 0 }}>
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
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1.2rem" }}>
              <button type="button" className="btn btn-primary" disabled={prefillBusy} onClick={onOpenCalculator}>
                {t("ref.openCalc")}
              </button>
              <Link className="btn btn-secondary" to="/app">{t("ref.toCalcBlank")}</Link>
            </div>
          </div>
          {detailSplit ? (
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
                    <th scope="col" className="num">{t("ref.colShareOfficial")}</th>
                    <th scope="col" className="num">{t("ref.colShareRenorm")}</th>
                    <th scope="col" className="num">{seatsColLabel}</th>
                    <th scope="col" className="num">{t("ref.colVotesEst")}</th>
                  </tr>
                </thead>
                <tbody>
                  {detailSplit.rows.map(({ party: p, renorm }) => (
                    <tr key={p.name}>
                      <td className="party-cell">{p.name}</td>
                      <td className="num">{p.vote_share != null ? `${p.vote_share.toFixed(2)}%` : "—"}</td>
                      <td className="num">{renorm != null ? `${renorm.toFixed(2)}%` : "—"}</td>
                      <td className="num">{p.seats_recorded ?? "—"}</td>
                      <td className="num">{p.votes_estimated ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
                {detailSplit.sumOfficial > 0 ? (
                  <tfoot>
                    <tr className="ref-detail-tfoot">
                      <th scope="row">{t("ref.rowTotal")}</th>
                      <td className="num">{detailSplit.sumOfficial.toFixed(2)}%</td>
                      <td className="num">100.00%</td>
                      <td className="num">{detailSplit.seatsCounted > 0 ? detailSplit.sumSeats : "—"}</td>
                      <td className="num">{detailSplit.votesCounted > 0 ? detailSplit.sumVotesEst : "—"}</td>
                    </tr>
                  </tfoot>
                ) : null}
              </table>
            </div>
          ) : null}
        </>
      ) : (
        <div className="ref-system-tab" style={{ maxWidth: "42rem" }}>
          {currentSummary ? (
            <>
              <p style={{ marginBottom: "0.5rem" }}>{summaryText}</p>
              {currentSummary.law_name && (
                <p className="muted" style={{ fontSize: "0.85em" }}>
                  {currentSummary.law_url ? (
                    <a href={currentSummary.law_url} target="_blank" rel="noopener noreferrer">
                      {t("ref.summaryLawSource", { name: currentSummary.law_name })}
                    </a>
                  ) : (
                    t("ref.summaryLawSource", { name: currentSummary.law_name })
                  )}
                </p>
              )}
              <button
                type="button"
                className="btn btn-sm"
                style={{ marginTop: "0.75rem" }}
                onClick={() => setShowModal(true)}
              >
                {t("ref.generateSummary")}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowModal(true)}
            >
              {t("ref.generateSummary")}
            </button>
          )}
        </div>
      )}

      {/* API key modal */}
      {showModal && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(0,0,0,0.45)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowModal(false); }}
        >
          <div style={{
            background: "var(--bg, #fff)", borderRadius: "8px", padding: "1.5rem",
            maxWidth: "22rem", width: "90%", boxShadow: "0 4px 24px rgba(0,0,0,0.18)",
          }}>
            <label className="field">
              <span>{t("ref.summaryApiKeyLabel")}</span>
              <input
                ref={apiKeyRef}
                type="password"
                placeholder={t("ref.summaryApiKeyPlaceholder")}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleGenerate(); }}
              />
            </label>
            {generateError && (
              <p style={{ color: "var(--error, #c00)", fontSize: "0.85em", marginTop: "0.4rem" }}>
                {generateError}
              </p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={generateBusy || !apiKey.trim()}
                onClick={() => void handleGenerate()}
              >
                {generateBusy ? t("ref.summaryGenerating") : t("ref.summaryGenerate")}
              </button>
              <button
                type="button"
                className="btn"
                disabled={generateBusy}
                onClick={() => { setShowModal(false); setGenerateError(null); }}
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function parlgovLoaded(s: Record<string, unknown> | null): boolean {
  const pg = s?.parlgov as Record<string, unknown> | undefined;
  return Boolean(pg?.loaded);
}

function cleaEnabled(s: Record<string, unknown> | null): boolean {
  const c = s?.clea as Record<string, unknown> | undefined;
  return Boolean(c?.enabled);
}

export function Reference() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const navigate = useNavigate();
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [countries, setCountries] = useState<ReferenceCountry[]>([]);
  const [countryId, setCountryId] = useState<number | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"" | "parlgov" | "clea">("");
  const [unifiedElections, setUnifiedElections] = useState<UnifiedElectionRow[]>([]);
  const [unifiedTotal, setUnifiedTotal] = useState(0);
  const [detail, setDetail] = useState<ReferenceElectionDetail | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listBusy, setListBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [prefillBusy, setPrefillBusy] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, CountrySummary>>({});

  const canLoadMore = useMemo(
    () => unifiedElections.length < unifiedTotal,
    [unifiedElections.length, unifiedTotal],
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
        const [list, sums] = await Promise.all([
          fetchReferenceCountries(),
          fetchSummaries().catch(() => ({} as Record<string, CountrySummary>)),
        ]);
        if (cancelled) return;
        setCountries(list);
        setSummaries(sums);
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

  const loadUnifiedElections = useCallback(
    async (nextOffset: number, append: boolean) => {
      setListBusy(true);
      setError(null);
      try {
        const res = await fetchUnifiedElections({
          countryId: typeof countryId === "number" ? countryId : undefined,
          limit: PAGE,
          offset: nextOffset,
          dateFrom: dateFrom.trim() || undefined,
          dateTo: dateTo.trim() || undefined,
          q: searchQ.trim() || undefined,
          source: sourceFilter || undefined,
        });
        setUnifiedTotal(res.total);
        setUnifiedElections((prev) => (append ? [...prev, ...res.items] : res.items));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setListBusy(false);
      }
    },
    [countryId, dateFrom, dateTo, searchQ, sourceFilter],
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
        setUnifiedElections([]);
        void loadUnifiedElections(0, false);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRefreshBusy(false);
      }
    },
    [formatRefreshPart, loadUnifiedElections],
  );

  useEffect(() => {
    if (!parlgovLoaded(status)) return;
    setUnifiedElections([]);
    setDetail(null);
    void loadUnifiedElections(0, false);
  }, [status, countryId, dateFrom, dateTo, searchQ, sourceFilter, loadUnifiedElections]);

  async function onPickElection(id: number, key: string, thresholdHint?: number | null) {
    if (selectedKey === key) {
      setSelectedKey(null);
      setDetail(null);
      return;
    }
    setSelectedKey(key);
    setDetailBusy(true);
    setError(null);
    try {
      const d = await fetchReferenceElectionDetail(id);
      setDetail({ ...d, source: "parlgov" });
      setThreshold(thresholdHint ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDetail(null);
    } finally {
      setDetailBusy(false);
    }
  }

  async function onPickUnified(row: UnifiedElectionRow) {
    if (row.source === "parlgov" && row.parlgov_election_id != null) {
      await onPickElection(row.parlgov_election_id, row.election_key, row.threshold_percent);
      return;
    }
    if (row.source === "clea") {
      await onPickCleaElection(row.election_key);
    }
  }

  async function onPickCleaElection(key: string) {
    if (selectedKey === key) {
      setSelectedKey(null);
      setDetail(null);
      return;
    }
    setSelectedKey(key);
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
            <a
              className="btn btn-secondary"
              href={referenceDuckdbDownloadHref()}
              download
            >
              {t("ref.downloadDuckdb")}
            </a>
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
              <label className="field">
                <span>{t("ref.filterSource")}</span>
                <select
                  value={sourceFilter}
                  onChange={(e) =>
                    setSourceFilter((e.target.value || "") as "" | "parlgov" | "clea")
                  }
                >
                  <option value="">{t("ref.filterSourceAll")}</option>
                  <option value="parlgov">{t("ref.filterSourceParlgov")}</option>
                  <option value="clea">{t("ref.filterSourceClea")}</option>
                </select>
              </label>
            </div>
            {status && !cleaEnabled(status) ? (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                {t("ref.cleaOptionalHint")}
              </p>
            ) : null}
          </section>

          <section className="panel">
            <h2 className="panel-title">{t("ref.electionsTitle")}</h2>
            {listBusy && !unifiedElections.length ? (
              <p className="muted">{t("ref.loadingList")}</p>
            ) : null}
            <div className="table-wrap">
              <table className="data table-ref-pick">
                <colgroup>
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "13%" }} />
                  <col style={{ width: "45%" }} />
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "8%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th>{t("ref.colKey")}</th>
                    <th>{t("ref.colDate")}</th>
                    <th>{t("ref.colCountry")}</th>
                    <th className="num">{t("ref.colSeats")}</th>
                    <th className="num">{t("ref.cleaColThr")}</th>
                    <th>{t("ref.colOpen")}</th>
                  </tr>
                </thead>
                <tbody>
                  {unifiedElections.map((row) => {
                    const isSelected = selectedKey === row.election_key;
                    return (
                      <>
                        <tr
                          key={row.election_key}
                          className={isSelected ? "ref-row-selected" : undefined}
                        >
                          <td className="muted">
                            {row.source === "parlgov" && row.parlgov_election_id != null
                              ? row.parlgov_election_id
                              : row.election_key}
                          </td>
                          <td>{row.election_date}</td>
                          <td>{row.election_label ?? "—"}</td>
                          <td className="num">{row.seats_total ?? "—"}</td>
                          <td className="num">
                            {row.threshold_percent != null
                              ? `${row.threshold_percent}%`
                              : "—"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className={`btn btn-sm${isSelected ? " btn-active" : ""}`}
                              onClick={() => void onPickUnified(row)}
                            >
                              {isSelected ? "▲" : t("ref.choose")}
                            </button>
                          </td>
                        </tr>
                        {isSelected ? (
                          <tr key={`${row.election_key}__detail`} className="ref-inline-detail-row">
                            <td colSpan={6} className="ref-inline-detail-cell">
                              {detailBusy ? (
                                <p className="muted">{t("ref.loadingDetail")}</p>
                              ) : detail ? (
                                <InlineDetail
                                  detail={detail}
                                  detailSplit={detailSplit}
                                  seatsColLabel={seatsColLabel}
                                  threshold={threshold}
                                  setThreshold={setThreshold}
                                  prefillBusy={prefillBusy}
                                  onOpenCalculator={() => void onOpenCalculator()}
                                  countrySummary={summaries[detail.country_code ?? ""] ?? null}
                                  lang={lang}
                                  onGenerateSummary={async (apiKey) => {
                                    const result = await postGenerateSummary({
                                      country_code: detail.country_code ?? "",
                                      country_name: detail.country_name ?? "",
                                      anthropic_key: apiKey,
                                    });
                                    setSummaries((prev) => ({
                                      ...prev,
                                      [detail.country_code ?? ""]: result,
                                    }));
                                    return result;
                                  }}
                                  t={t}
                                />
                              ) : null}
                            </td>
                          </tr>
                        ) : null}
                      </>
                    );
                  })}
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
                  onClick={() => void loadUnifiedElections(unifiedElections.length, true)}
                >
                  {t("ref.loadMore")}
                </button>
              </p>
            ) : null}
          </section>

        </>
      ) : null}

      <p className="muted" style={{ marginTop: "2rem" }}>
        <Link to="/">{t("nav.landing")}</Link>
      </p>
    </article>
  );
}
