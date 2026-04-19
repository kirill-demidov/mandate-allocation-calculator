import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { CalculatorPrefillState } from "../types/calculatorPrefill";

type PartyVotesRow = { id: string; name: string; votes: string };

function newRow(): PartyVotesRow {
  return { id: crypto.randomUUID(), name: "", votes: "" };
}

function parseIntVotes(s: string): number | null {
  const t = String(s).trim().replace(/\s+/g, "").replace(/,/g, "");
  if (!t) return null;
  const n = Number(t);
  if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) return null;
  return n;
}

/** Доли в % от суммы голосов; последняя партия получает остаток до 100. */
function votesToPercents(
  rows: { name: string; votes: number }[],
): { name: string; votePercent: string }[] {
  const total = rows.reduce((a, r) => a + r.votes, 0);
  if (total <= 0) return [];
  const prec = 8;
  const out: { name: string; votePercent: string }[] = [];
  let allocated = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (i < rows.length - 1) {
      const p = (r.votes / total) * 100;
      const rounded = Number(p.toFixed(prec));
      allocated += rounded;
      out.push({ name: r.name, votePercent: String(rounded) });
    } else {
      out.push({
        name: r.name,
        votePercent: String(Number((100 - allocated).toFixed(prec))),
      });
    }
  }
  return out;
}

export function AbsoluteVotesForm() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [mandates, setMandates] = useState(225);
  const [threshold, setThreshold] = useState(5);
  const [rows, setRows] = useState<PartyVotesRow[]>([
    { id: crypto.randomUUID(), name: "", votes: "" },
    { id: crypto.randomUUID(), name: "", votes: "" },
  ]);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => {
    const parties: { name: string; votes: number }[] = [];
    for (const r of rows) {
      const name = r.name.trim();
      if (!name) continue;
      const v = parseIntVotes(r.votes);
      if (v === null) return null;
      parties.push({ name, votes: v });
    }
    const total = parties.reduce((a, p) => a + p.votes, 0);
    return { parties, total };
  }, [rows]);

  const preview = useMemo(() => {
    if (!parsed || parsed.parties.length === 0 || parsed.total <= 0) return null;
    return votesToPercents(parsed.parties);
  }, [parsed]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!parsed || parsed.parties.length === 0) {
      setError(t("votesForm.errNeedParty"));
      return;
    }
    if (parsed.total <= 0) {
      setError(t("votesForm.errTotalVotes"));
      return;
    }
    if (!Number.isFinite(mandates) || mandates < 1) {
      setError(t("votesForm.errMandates"));
      return;
    }
    const percents = votesToPercents(parsed.parties);
    const state: CalculatorPrefillState = {
      totalMandates: mandates,
      thresholdPercent: threshold,
      parties: percents,
    };
    navigate("/app", { state });
  }

  return (
    <article className="page-votes">
      <h1>{t("votesForm.title")}</h1>
      <p className="lead">{t("votesForm.lead")}</p>
      <p>{t("votesForm.how")}</p>

      <form onSubmit={onSubmit}>
        <section className="panel">
          <h2 className="panel-title">{t("votesForm.sectionParams")}</h2>
          <div className="grid-votes-params">
            <label className="field">
              <span>{t("votesForm.mandates")}</span>
              <input
                type="number"
                min={1}
                max={10000}
                value={mandates}
                onChange={(e) => setMandates(Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>{t("votesForm.threshold")}</span>
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
          <h2 className="panel-title">{t("votesForm.sectionParties")}</h2>
          <p className="muted">{t("votesForm.votesHint")}</p>

          <div className="table-wrap">
            <table className="data table-votes">
              <colgroup>
                <col style={{ width: "58%" }} />
                <col style={{ width: "28%" }} />
                <col style={{ width: "14%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>{t("votesForm.colParty")}</th>
                  <th className="num">{t("votesForm.colVotes")}</th>
                  <th className="actions-cell" aria-hidden />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="party-cell">
                      <input
                        className="form-input"
                        value={r.name}
                        onChange={(e) =>
                          setRows((prev) =>
                            prev.map((x) =>
                              x.id === r.id ? { ...x, name: e.target.value } : x,
                            ),
                          )
                        }
                      />
                    </td>
                    <td className="num">
                      <input
                        className="form-input form-input--votes"
                        inputMode="numeric"
                        value={r.votes}
                        onChange={(e) =>
                          setRows((prev) =>
                            prev.map((x) =>
                              x.id === r.id ? { ...x, votes: e.target.value } : x,
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
                          setRows((prev) => (prev.length > 1 ? prev.filter((x) => x.id !== r.id) : prev))
                        }
                      >
                        {t("votesForm.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="row-actions">
            <button type="button" className="btn" onClick={() => setRows((p) => [...p, newRow()])}>
              {t("votesForm.addParty")}
            </button>
          </div>
        </section>

        {parsed && parsed.parties.length > 0 ? (
          <section className="panel">
            <h2 className="panel-title">{t("votesForm.previewTitle")}</h2>
            <p className="muted">{t("votesForm.previewTotal", { total: parsed.total })}</p>
            {preview ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("votesForm.colParty")}</th>
                      <th className="num">{t("votesForm.colVotes")}</th>
                      <th className="num">{t("votesForm.colPercent")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parsed.parties.map((p, i) => (
                      <tr key={p.name}>
                        <td>{p.name}</td>
                        <td className="num">{p.votes}</td>
                        <td className="num">
                          {preview[i] ? Number(preview[i].votePercent).toFixed(4) : "—"}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        ) : null}

        {error ? <div className="error">{error}</div> : null}

        <p className="row-actions row-actions--footer">
          <button type="submit" className="btn btn-primary">
            {t("votesForm.submit")}
          </button>
          <Link className="btn btn-secondary" to="/app">
            {t("votesForm.toCalcManual")}
          </Link>
        </p>
      </form>
    </article>
  );
}
