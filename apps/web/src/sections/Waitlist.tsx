import "./Waitlist.css";
import { useState, type FormEvent } from "react";
import { joinWaitlist } from "../lib/api.ts";

// Verbatim copy from the mockup source (docs/mockups/source/sections-2.jsx, Waitlist).
export const WAITLIST_COPY = {
  eyebrow: "Enter the World",
  lede: "Closed playtest opens in waves through 2026. Drop your email and we'll send a Veil-key when your cohort opens — no marketing churn, just the keys.",
  placeholder: "your.true.name@aethos",
  submit: "Request Veil-Key →",
  metaCount: "4,287 wanderers on the list",
  metaWave: "Next wave · Q3 2026",
  successLabel: "A whisper, received",
  successMsg: "“The gods know your name. Listen for the bell.”",
} as const;

type Status = "idle" | "submitting" | "success" | "error";

// "09 / Enter the World" section: the closing waitlist form. Interactive (not reveal-gated — matches
// the AudioDemo precedent). State is hydration-safe: it starts idle/empty so the server-rendered
// form matches the first client render; the network call happens only inside the post-hydration
// submit handler. joinWaitlist (api.ts) maps every outcome to a handled result, so a failure shows a
// calm inline message rather than throwing. Renders id="waitlist"; once the capstone mounts this in
// App.tsx, the existing NavBar + Hero href="#waitlist" CTAs become live (resolves e87752a8d7c3).
export function Waitlist() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (status === "submitting") return;
    setStatus("submitting");
    const result = await joinWaitlist(email);
    if (result.ok) {
      setStatus("success");
    } else {
      setError(result.error ?? "Something went wrong.");
      setStatus("error");
    }
  };

  return (
    <section className="waitlist" id="waitlist">
      <div className="waitlist__inner">
        <p className="waitlist__eyebrow">
          <span className="waitlist__eyebrow-num">09</span> {WAITLIST_COPY.eyebrow}
        </p>
        <h2 className="waitlist__title">
          The trial begins <em>when the seal is broken.</em>
        </h2>
        <p className="waitlist__lede">{WAITLIST_COPY.lede}</p>

        <div className="waitlist__wrap">
          {status === "success" ? (
            <div className="waitlist__success">
              <div className="waitlist__success-label">{WAITLIST_COPY.successLabel}</div>
              <div className="waitlist__success-msg">{WAITLIST_COPY.successMsg}</div>
            </div>
          ) : (
            <>
              <form className="waitlist__form" onSubmit={(e) => void onSubmit(e)}>
                <input
                  className="waitlist__input"
                  type="email"
                  required
                  placeholder={WAITLIST_COPY.placeholder}
                  aria-label="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <button
                  className="waitlist__submit"
                  type="submit"
                  disabled={status === "submitting"}
                >
                  {WAITLIST_COPY.submit}
                </button>
              </form>
              {status === "error" ? (
                <p className="waitlist__error" role="alert">
                  {error}
                </p>
              ) : (
                <div className="waitlist__meta">
                  <span>{WAITLIST_COPY.metaCount}</span>
                  <span>{WAITLIST_COPY.metaWave}</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
