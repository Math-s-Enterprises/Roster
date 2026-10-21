import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import AuthShell from "@/components/AuthShell";

/**
 * Confirm email: reached from the link in the sign-up email.
 *
 * This is where the account is really created. The page asks the server to confirm the link once,
 * as soon as it opens, and on success the person is signed in and taken into the app.
 *
 * It is not wrapped in PublicOnly: the link has to work even if somebody else is already signed in
 * on this browser (confirming simply signs in the new account).
 */
export default function VerifyEmail() {
  const { verifyEmail } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [state, setState] = useState(token ? "working" : "missing"); // working | missing | failed
  const [message, setMessage] = useState(null);
  // A link is single-use, so it must be sent once only. In development React runs effects twice.
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    verifyEmail(token)
      .then(() => navigate("/", { replace: true }))
      .catch((err) => {
        setState("failed");
        setMessage(errorMessage(err, "We could not confirm your email. Please try the link again."));
      });
  }, [token, verifyEmail, navigate]);

  return (
    <AuthShell>
      <section className="si-card" data-testid="verify-email" aria-live="polite">
        {state === "working" && (
          <>
            <h2 className="si-h2">Confirming your email</h2>
            <p className="si-card-sub" role="status">
              <span className="si-spinner" aria-hidden="true" /> One moment while we create your account.
            </p>
          </>
        )}
        {state === "missing" && (
          <>
            <h2 className="si-h2">This link is incomplete</h2>
            <p className="si-card-sub">
              Open the link from your email again, making sure the whole address came across. Or go back
              and sign up to get a new one.
            </p>
          </>
        )}
        {state === "failed" && (
          <>
            <h2 className="si-h2">We could not confirm your email</h2>
            <p className="si-form-error" role="alert" data-testid="verify-email-error">{message}</p>
          </>
        )}
        {state !== "working" && (
          <p className="si-note">
            <Link to="/login" data-testid="verify-email-login-link" className="si-link">
              Back to sign in or sign up
            </Link>
          </p>
        )}
      </section>
    </AuthShell>
  );
}
