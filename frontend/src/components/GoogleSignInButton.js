import React, { useEffect, useRef, useState } from "react";

const GSI_SRC = "https://accounts.google.com/gsi/client";

/**
 * Loads Google Identity Services once and caches the promise, so several
 * mounts (or a remount) don't inject the script repeatedly.
 */
let gsiPromise = null;
function loadGoogleScript() {
  if (gsiPromise) return gsiPromise;
  gsiPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve(window.google);

    const existing = document.querySelector(`script[src="${GSI_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve(window.google));
      existing.addEventListener("error", reject);
      return;
    }

    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve(window.google);
    script.onerror = () => reject(new Error("Could not load Google sign-in"));
    document.head.appendChild(script);
  });
  return gsiPromise;
}

/**
 * Renders Google's own sign-in button.
 *
 * Google hands us a signed ID token in the callback; we pass it straight to
 * onCredential, which sends it to the backend for verification. The token is
 * never trusted client-side — it's just a bearer of claims until the server
 * checks its signature.
 */
export default function GoogleSignInButton({ clientId, onCredential, disabled }) {
  const containerRef = useRef(null);
  const callbackRef = useRef(onCredential);
  const [error, setError] = useState(null);

  // Keep the latest callback without re-initialising the button each render.
  useEffect(() => {
    callbackRef.current = onCredential;
  }, [onCredential]);

  useEffect(() => {
    if (!clientId || !containerRef.current) return;
    let cancelled = false;

    loadGoogleScript()
      .then((google) => {
        if (cancelled || !containerRef.current) return;
        google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => callbackRef.current?.(response.credential),
        });
        google.accounts.id.renderButton(containerRef.current, {
          theme: "filled_black",
          size: "large",
          shape: "pill",
          width: containerRef.current.offsetWidth || 320,
          text: "continue_with",
        });
      })
      .catch((err) => !cancelled && setError(err.message));

    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (!clientId) return null;

  if (error) {
    return <p className="text-xs text-red-400 text-center">{error}</p>;
  }

  return (
    <div
      ref={containerRef}
      data-testid="google-signin"
      className={`flex justify-center ${disabled ? "pointer-events-none opacity-50" : ""}`}
    />
  );
}
