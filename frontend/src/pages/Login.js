import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { LogIn, Sparkles, UserPlus } from "lucide-react";

import { Link } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import GoogleSignInButton from "@/components/GoogleSignInButton";
import { LOGIN } from "@/constants/testIds/auth";

const HERO_IMAGE =
  "https://images.unsplash.com/photo-1552925766-63ab07391e02?crop=entropy&cs=srgb&fm=jpg&w=1600&q=70";

const FEATURES = ["Age curfews", "Hour caps", "Fixed shifts", "Full-day coverage"];

export default function Login() {
  const { login, signup, loginWithGoogle, providers } = useAuth();
  const navigate = useNavigate();

  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", shopName: "" });
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";
  const update = (field) => (event) =>
    setForm((prev) => ({ ...prev, [field]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (isSignup) {
        await signup({
          email: form.email,
          password: form.password,
          name: form.name,
          shop_name: form.shopName,
        });
      } else {
        await login(form.email, form.password);
      }
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(errorMessage(err, "Could not sign you in"));
    } finally {
      setBusy(false);
    }
  };

  const handleGoogleCredential = async (credential) => {
    setBusy(true);
    try {
      await loginWithGoogle(credential);
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(errorMessage(err, "Google sign-in failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex items-center">
      <div
        className="absolute inset-0 -z-10 opacity-30"
        style={{
          backgroundImage: `url('${HERO_IMAGE}')`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
      <div className="absolute inset-0 -z-10 bg-black/80" />

      <div className="max-w-6xl mx-auto w-full px-8 grid md:grid-cols-2 gap-12 items-center">
        <div className="space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass text-xs text-cyan-400">
            <Sparkles size={12} /> AI-assisted workforce scheduling
          </div>
          <h1 className="text-5xl lg:text-6xl font-light tracking-tight">
            Fully covered <span className="neon-text font-bold">weekly rosters</span> in
            under five minutes.
          </h1>
          <p className="text-white/60 max-w-md text-lg">
            Set up your shop, staff and policies. Roster schedules the team while
            respecting every legal limit, holiday and preference — and never leaves the
            shop unattended.
          </p>
          <div className="flex flex-wrap gap-3 pt-4">
            {FEATURES.map((feature) => (
              <div key={feature} className="px-3 py-1.5 rounded-full glass text-xs text-white/70">
                {feature}
              </div>
            ))}
          </div>
        </div>

        <div className="glass rounded-3xl p-8 md:p-10">
          <div className="flex gap-2 mb-8 bg-white/5 p-1 rounded-full w-fit">
            <button
              type="button"
              data-testid="tab-login"
              className={`px-4 py-1.5 rounded-full text-sm ${!isSignup ? "neon-btn" : "text-white/60"}`}
              onClick={() => setMode("login")}
            >
              Log in
            </button>
            <button
              type="button"
              data-testid="tab-signup"
              className={`px-4 py-1.5 rounded-full text-sm ${isSignup ? "neon-btn" : "text-white/60"}`}
              onClick={() => setMode("signup")}
            >
              Sign up
            </button>
          </div>

          <form onSubmit={submit} className="space-y-4">
            {isSignup && (
              <>
                <Field label="Your name">
                  <input
                    data-testid="input-name"
                    required
                    value={form.name}
                    onChange={update("name")}
                    className="mt-1 w-full px-4 py-3 rounded-xl"
                    autoComplete="name"
                  />
                </Field>
                <Field label="Shop name">
                  <input
                    data-testid="input-shop"
                    required
                    value={form.shopName}
                    onChange={update("shopName")}
                    className="mt-1 w-full px-4 py-3 rounded-xl"
                    placeholder="e.g. Metro Tech Retail"
                    autoComplete="organization"
                  />
                </Field>
              </>
            )}

            <Field label="Email">
              <input
                data-testid="input-email"
                required
                type="email"
                value={form.email}
                onChange={update("email")}
                className="mt-1 w-full px-4 py-3 rounded-xl"
                autoComplete="email"
              />
            </Field>

            <Field
              label="Password"
              action={
                !isSignup && (
                  <Link
                    to="/forgot-password"
                    data-testid={LOGIN.forgotPasswordLink}
                    className="text-[11px] text-cyan-400 hover:text-cyan-300"
                  >
                    Forgot password?
                  </Link>
                )
              }
            >
              <input
                data-testid="input-password"
                required
                type="password"
                minLength={isSignup ? 8 : undefined}
                value={form.password}
                onChange={update("password")}
                className="mt-1 w-full px-4 py-3 rounded-xl"
                autoComplete={isSignup ? "new-password" : "current-password"}
              />
              {isSignup && (
                <p className="text-[11px] text-white/40 mt-1">At least 8 characters.</p>
              )}
            </Field>

            <button
              type="submit"
              data-testid="submit-auth"
              disabled={busy}
              className="neon-btn w-full py-3 rounded-full flex items-center justify-center gap-2 mt-6 disabled:opacity-60"
            >
              {isSignup ? <UserPlus size={16} /> : <LogIn size={16} />}
              {busy ? "Please wait…" : isSignup ? "Create account" : "Sign in"}
            </button>
          </form>

          {/* Only shown when the backend reports Google sign-in is configured,
              so users never see a button that cannot work. */}
          {providers.google && providers.google_client_id && (
            <>
              <div className="my-6 flex items-center gap-3 text-xs text-white/40">
                <div className="flex-1 h-px bg-white/10" /> or
                <div className="flex-1 h-px bg-white/10" />
              </div>
              <GoogleSignInButton
                clientId={providers.google_client_id}
                onCredential={handleGoogleCredential}
                disabled={busy}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const Field = ({ label, children, action }) => (
  <div>
    <div className="flex items-center justify-between">
      <label className="text-xs text-white/60">{label}</label>
      {action}
    </div>
    {children}
  </div>
);
