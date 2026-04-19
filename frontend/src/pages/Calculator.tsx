import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";
import { calculate, downloadExcel } from "../api/client";
import type { CalculateRequest, MandateRow } from "../api/types";
import type { CalculatorPrefillState } from "../types/calculatorPrefill";
import { isPercentSumOver100, sumVotePercentsNamedOnly } from "../utils/percentSum";

type PartyDraft = { id: string; name: string; votePercent: string };

function newParty(): PartyDraft {
  return { id: crypto.randomUUID(), name: "", votePercent: "" };
}

function parsePct(s: string): number | null {
  const v = Number(String(s).replace(",", "."));
  if (!Number.isFinite(v)) return null;
  return v;
}

function Paragraphs({ text }: { text: string }) {
  const parts = text.split(/\n\n+/);
  return (
    <>
      {parts.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </>
  );
}

type MethodLinkItem = { label: string; href: string };

function MethodReadMore({ methodKey }: { methodKey: string }) {
  const { t } = useTranslation();
  const raw = t(`methods.${methodKey}.links`, { returnObjects: true }) as unknown;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const links: MethodLinkItem[] = [];
  for (const item of raw) {
    if (
      item &&
      typeof item === "object" &&
      typeof (item as MethodLinkItem).label === "string" &&
      typeof (item as MethodLinkItem).href === "string"
    ) {
      links.push(item as MethodLinkItem);
    }
  }
  if (!links.length) return null;
  return (
    <div className="method-readmore">
      <p className="method-readmore-title">{t("calc.methodLinksHeading")}</p>
      <ul className="method-links">
        {links.map((link) => (
          <li key={link.href}>
            <a href={link.href} target="_blank" rel="noopener noreferrer">
              {link.label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function BarChart({
  rows,
  valueKey,
  label,
}: {
  rows: MandateRow[];
  valueKey: keyof MandateRow;
  label: string;
}) {
  const nums = rows.map((r) => Number(r[valueKey] as number));
  const max = Math.max(1e-9, ...nums.map((n) => Math.abs(n)));
  return (
    <div className="panel" aria-label={label}>
      <h3>{label}</h3>
      {rows.map((r) => {
        const v = Number(r[valueKey] as number);
        const w = Math.round((v / max) * 100);
        return (
          <div key={r.party} style={{ marginBottom: "0.65rem" }}>
            <div className="muted" style={{ marginBottom: "0.2rem" }}>
              {r.party} — {v.toFixed(2)}
              {valueKey === "vote_percent" ? "%" : ""}
            </div>
            <div
              style={{
                height: 10,
                background: "#ece7dd",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${w}%`,
                  height: "100%",
                  background: "var(--accent)",
                  opacity: 0.85,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MandateHeat({
  rows,
  keys,
  labels,
}: {
  rows: MandateRow[];
  keys: (keyof MandateRow)[];
  labels: string[];
}) {
  const matrix = rows.map((r) => keys.map((k) => Number(r[k] as number)));
  const flat = matrix.flat();
  const max = Math.max(1, ...flat);
  return (
    <div className="panel">
      <div className="table-wrap">
        <table className="data data-results data-results--heat">
          <colgroup>
            <col className="data-results__party" />
            {keys.map((k) => (
              <col key={String(k)} className="data-results__method" />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col">{labels[0]}</th>
              {keys.map((_, i) => (
                <th key={labels[i + 1]} scope="col" className="num">
                  {labels[i + 1]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={r.party}>
                <td className="data-results__party-cell">{r.party}</td>
                {keys.map((k, ki) => {
                  const v = matrix[ri][ki];
                  const alpha = 0.12 + (v / max) * 0.55;
                  return (
                    <td
                      key={String(k)}
                      className="num"
                      style={{ background: `rgba(31, 58, 95, ${alpha})` }}
                    >
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Calculator() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const lang = i18n.language === "en" ? "en" : "ru";

  const [mandates, setMandates] = useState(120);
  const [threshold, setThreshold] = useState(5);
  const [parties, setParties] = useState<PartyDraft[]>([
    { id: crypto.randomUUID(), name: "Party A", votePercent: "35" },
    { id: crypto.randomUUID(), name: "Party B", votePercent: "28" },
    { id: crypto.randomUUID(), name: "Party C", votePercent: "22" },
    { id: crypto.randomUUID(), name: "Party D", votePercent: "15" },
  ]);
  const [result, setResult] = useState<MandateRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const s = location.state as CalculatorPrefillState | undefined;
    if (!s?.parties?.length) return;
    setMandates(s.totalMandates);
    setThreshold(s.thresholdPercent);
    setParties(
      s.parties.map((p) => ({
        id: crypto.randomUUID(),
        name: p.name,
        votePercent: p.votePercent,
      })),
    );
    setResult(null);
    setError(null);
  }, [location.state]);

  const sumPct = useMemo(() => sumVotePercentsNamedOnly(parties), [parties]);

  const requestBody = useMemo((): CalculateRequest | null => {
    const ps: { name: string; vote_percent: number }[] = [];
    for (const p of parties) {
      const name = p.name.trim();
      if (!name) continue;
      const vp = parsePct(p.votePercent);
      if (vp === null || vp < 0) return null;
      ps.push({ name, vote_percent: vp });
    }
    if (!ps.length) return null;
    return {
      total_mandates: mandates,
      threshold_percent: threshold,
      parties: ps,
    };
  }, [parties, mandates, threshold]);

  async function onCalculate() {
    setError(null);
    if (!requestBody) {
      setError(t("calc.needParty"));
      return;
    }
    if (isPercentSumOver100(sumPct)) {
      setError(t("calc.sumError"));
      return;
    }
    setBusy(true);
    try {
      const res = await calculate(requestBody);
      setResult(res.rows);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onExport() {
    if (!requestBody) return;
    setError(null);
    setBusy(true);
    try {
      await downloadExcel(requestBody, lang);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <p className="muted calc-switch">
        <Link to="/app/votes">{t("calc.fromVotesLink")}</Link>
      </p>
      <h1>{t("calc.title")}</h1>

      <section className="panel">
        <h2 className="panel-title">{t("calc.settings")}</h2>
        <div className="grid-2">
          <label className="field">
            <span>{t("calc.mandates")}</span>
            <input
              type="number"
              min={1}
              max={10000}
              value={mandates}
              onChange={(e) => setMandates(Number(e.target.value))}
            />
          </label>
          <label className="field">
            <span>{t("calc.threshold")}</span>
            <input
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </label>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">{t("calc.parties")}</h2>
        <p className="muted">
          {t("calc.sumVotes")}: {sumPct.toFixed(2)}%
        </p>
        {isPercentSumOver100(sumPct) ? <div className="error">{t("calc.sumError")}</div> : null}

        <div className="table-wrap">
          <table className="data data-calc-parties">
            <colgroup>
              <col className="data-calc-parties__name" />
              <col className="data-calc-parties__pct" />
              <col className="data-calc-parties__act" />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">{t("calc.partyName")}</th>
                <th scope="col" className="num">
                  {t("calc.votesPct")}
                </th>
                <th scope="col" className="data-calc-parties__head-act" aria-hidden />
              </tr>
            </thead>
            <tbody>
              {parties.map((p) => (
                <tr key={p.id}>
                  <td className="party-cell">
                    <input
                      className="form-input"
                      value={p.name}
                      onChange={(e) =>
                        setParties((prev) =>
                          prev.map((x) =>
                            x.id === p.id ? { ...x, name: e.target.value } : x,
                          ),
                        )
                      }
                    />
                  </td>
                  <td className="num data-calc-parties__pct-cell">
                    <input
                      className="form-input form-input--votes-inline"
                      inputMode="decimal"
                      value={p.votePercent}
                      onChange={(e) =>
                        setParties((prev) =>
                          prev.map((x) =>
                            x.id === p.id
                              ? { ...x, votePercent: e.target.value }
                              : x,
                          ),
                        )
                      }
                    />
                  </td>
                  <td className="actions-cell">
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() =>
                        setParties((prev) => prev.filter((x) => x.id !== p.id))
                      }
                    >
                      {t("calc.remove")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="row-actions">
          <button
            type="button"
            className="btn"
            onClick={() => setParties((prev) => [...prev, newParty()])}
          >
            {t("calc.addParty")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || isPercentSumOver100(sumPct)}
            onClick={() => void onCalculate()}
          >
            {t("calc.calculate")}
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !requestBody || isPercentSumOver100(sumPct)}
            onClick={() => void onExport()}
          >
            {t("calc.export")}
          </button>
        </div>
      </section>

      {error ? <div className="error">{error}</div> : null}

      {result ? (
        <>
          <h2 id="results">{t("calc.results")}</h2>
          <div className="table-wrap">
            <table className="data data-results" aria-labelledby="results">
              <colgroup>
                <col className="data-results__party" />
                <col className="data-results__pct" />
                <col className="data-results__method" />
                <col className="data-results__method" />
                <col className="data-results__method" />
                <col className="data-results__method" />
                <col className="data-results__method" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">{t("table.party")}</th>
                  <th scope="col" className="num">
                    {t("table.votes")}
                  </th>
                  <th scope="col" className="num">
                    {t("table.hare")}
                  </th>
                  <th scope="col" className="num">
                    {t("table.droop")}
                  </th>
                  <th scope="col" className="num">
                    {t("table.sl")}
                  </th>
                  <th scope="col" className="num">
                    {t("table.dhondt")}
                  </th>
                  <th scope="col" className="num">
                    {t("table.imp")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.map((r) => (
                  <tr key={r.party}>
                    <td className="data-results__party-cell">{r.party}</td>
                    <td className="num">{r.vote_percent.toFixed(2)}</td>
                    <td className="num">{r.hare}</td>
                    <td className="num">{r.droop}</td>
                    <td className="num">{r.sainte_lague}</td>
                    <td className="num">{r.dhondt}</td>
                    <td className="num">{r.imperiali}</td>
                  </tr>
                ))}
                <tr>
                  <td className="data-results__party-cell">
                    <strong>{t("table.total")}</strong>
                  </td>
                  <td className="num">
                    <strong>
                      {result.reduce((a, r) => a + r.vote_percent, 0).toFixed(2)}
                    </strong>
                  </td>
                  {(["hare", "droop", "sainte_lague", "dhondt", "imperiali"] as const).map(
                    (k) => (
                      <td key={k} className="num">
                        <strong>
                          {result.reduce((a, r) => a + Number(r[k] as number), 0)}
                        </strong>
                      </td>
                    ),
                  )}
                </tr>
              </tbody>
            </table>
          </div>

          <BarChart rows={result} valueKey="vote_percent" label={t("calc.chartVotes")} />

          <h3>{t("calc.chartMandates")}</h3>
          <MandateHeat
            rows={result}
            keys={["hare", "droop", "sainte_lague", "dhondt", "imperiali"]}
            labels={[
              t("table.party"),
              t("table.hare"),
              t("table.droop"),
              t("table.sl"),
              t("table.dhondt"),
              t("table.imp"),
            ]}
          />

          <h2 id="methods">{t("calc.methodsHeading")}</h2>
          {(
            [
              "hare",
              "droop",
              "sl",
              "dhondt",
              "imp",
            ] as const
          ).map((key) => (
            <section key={key} className="method-block panel">
              <h3>{t(`methods.${key}.title`)}</h3>
              <Paragraphs text={t(`methods.${key}.body`)} />
              <MethodReadMore methodKey={key} />
            </section>
          ))}
        </>
      ) : null}
    </article>
  );
}
