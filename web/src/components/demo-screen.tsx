"use client";

import Link from "next/link";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { parseDemo } from "@/lib/demo";
import { dateTime } from "@/lib/format";
import { useResource } from "@/lib/use-resource";
import { useEnvironment } from "./app-shell";
import { ErrorNotice, Loading } from "./ui";
import styles from "./demo-screen.module.css";

const stops = {
  instruments: [
    "Inspect the saved quote timestamps and missing prices.",
    "Compare cash, shares, a call and a call spread under the same assumptions.",
    "See how premium, fees and position size change the result.",
  ],
  forecasts: [
    "Read the probability, baseline and outcome rules recorded in advance.",
    "Open the exact source behind the outcome and its correction.",
    "See the score change while the original decision stays in the history.",
  ],
};

export function DemoScreen() {
  const demo = useResource("/demo", parseDemo);
  const { capabilities, capabilityError } = useEnvironment();
  const ready = capabilities?.read_only && demo.data && !demo.error;
  return (
    <div className={`page ${styles.page}`}>
      <header className={styles.header}>
        <div className="eyebrow">RESEARCHDESK / INTERACTIVE WALKTHROUGH</div>
        <h1>
          Follow a decision.
          <br />
          Inspect what supports it.
        </h1>
        <p>
          Two short paths through the research workbench: choosing how to
          express a thesis, then checking a forecast against its eventual
          outcome.
        </p>
        <div className={styles.label}>
          <LockKeyhole size={14} /> Read-only demonstration · synthetic inputs
        </div>
      </header>
      {capabilityError && <ErrorNotice>{capabilityError}</ErrorNotice>}
      {demo.error && (
        <ErrorNotice onRetry={() => void demo.refresh()}>
          This server has no verified demo package available. Start the
          dedicated demo viewer, then reload this page. Your research workspace
          is still available from the navigation.
        </ErrorNotice>
      )}
      {capabilities && !capabilities.read_only && (
        <ErrorNotice>
          This is an operator workspace. Open the separate read-only demo viewer
          to follow this walkthrough.
        </ErrorNotice>
      )}
      {demo.loading && <Loading label="Loading the verified demonstration…" />}
      {ready && demo.data && (
        <>
          <div className={styles.cards}>
            {[...demo.data.walkthroughs]
              .sort((a) => (a.id === "instruments" ? -1 : 1))
              .map((item, index) => (
                <article className={styles.card} key={item.id}>
                  <div className={styles.number}>
                    0{index + 1} /{" "}
                    {item.id === "instruments"
                      ? "EXPRESSION"
                      : "ACCOUNTABILITY"}
                  </div>
                  <h2>
                    {item.id === "instruments"
                      ? "A bullish view has a price."
                      : "A forecast needs an outcome."}
                  </h2>
                  <p>{item.description}</p>
                  <ol>
                    {stops[item.id].map((stop) => (
                      <li key={stop}>{stop}</li>
                    ))}
                  </ol>
                  <Link className={styles.link} href={item.href}>
                    {item.id === "instruments"
                      ? "Inspect the comparison"
                      : "Follow the forecast"}
                    <ArrowRight size={17} />
                  </Link>
                </article>
              ))}
          </div>
          <section className={styles.scope} aria-labelledby="demo-scope">
            <div>
              <h2 id="demo-scope">What you’re looking at</h2>
              <p>
                The application computes these reports and checks their source
                links using invented prices, reports and probabilities. Each
                package is built from scratch, separately from the operator’s
                research.
              </p>
            </div>
            <div>
              <h3>What remains to be demonstrated</h3>
              <p>
                No model is running here. These examples do not measure agent
                research quality, establish an investment edge or simulate
                options execution. The paper account is uninitialized.
              </p>
            </div>
          </section>
          <div className={styles.footer}>
            <span>
              Package built {dateTime(demo.data.built_at)}. Time-based forecast
              states continue to age.
            </span>
            <Link href="/">
              Browse the recorded cases <ArrowRight size={14} />
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
