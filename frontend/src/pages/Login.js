import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Sparkles, LogIn, UserPlus, Store } from "lucide-react";

export default function Login() {
  const { login, signup } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("aneeshthimmapurmath@gmail.com");
  const [password, setPassword] = useState("demo1234");
  const [name, setName] = useState("");
  const [shopName, setShopName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await signup({ email, password, name, shop_name: shopName });
      }
      toast.success("Welcome to Roster AI");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Auth failed");
    } finally {
      setBusy(false);
    }
  };

  const google = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex items-center">
      <div
        className="absolute inset-0 -z-10 opacity-30"
        style={{
          backgroundImage: `url('https://images.unsplash.com/photo-1552925766-63ab07391e02?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA2ODl8MHwxfHNlYXJjaHwxfHxmdXR1cmlzdGljJTIwcmV0YWlsJTIwc3RvcmUlMjBkYXJrfGVufDB8fHx8MTc4NTI3MzQxMHww&ixlib=rb-4.1.0&q=85')`,
          backgroundSize: "cover", backgroundPosition: "center",
        }}
      />
      <div className="absolute inset-0 -z-10 bg-black/80" />

      <div className="max-w-6xl mx-auto w-full px-8 grid md:grid-cols-2 gap-12 items-center">
        <div className="space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass text-xs text-cyan-400">
            <Sparkles size={12} /> AI-Powered Workforce Scheduling
          </div>
          <h1 className="text-5xl lg:text-6xl font-light tracking-tight">
            Fully compliant <span className="neon-text font-bold">weekly rosters</span> in under 5 minutes.
          </h1>
          <p className="text-white/60 max-w-md text-lg">
            Configure your shop, staff, and policies. Let Roster AI schedule your team while
            respecting every rule, holiday, and preference.
          </p>
          <div className="flex flex-wrap gap-3 pt-4">
            {["Age curfews", "Hour caps", "Fixed shifts", "Custom rules"].map((f) => (
              <div key={f} className="px-3 py-1.5 rounded-full glass text-xs text-white/70">{f}</div>
            ))}
          </div>
        </div>

        <div className="glass rounded-3xl p-8 md:p-10">
          <div className="flex gap-2 mb-8 bg-white/5 p-1 rounded-full w-fit">
            <button
              data-testid="tab-login"
              className={`px-4 py-1.5 rounded-full text-sm ${mode === "login" ? "neon-btn" : "text-white/60"}`}
              onClick={() => setMode("login")}
            >Login</button>
            <button
              data-testid="tab-signup"
              className={`px-4 py-1.5 rounded-full text-sm ${mode === "signup" ? "neon-btn" : "text-white/60"}`}
              onClick={() => setMode("signup")}
            >Sign up</button>
          </div>

          <form onSubmit={submit} className="space-y-4">
            {mode === "signup" && (
              <>
                <div>
                  <label className="text-xs text-white/60">Your name</label>
                  <input data-testid="input-name" required value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full px-4 py-3 rounded-xl" />
                </div>
                <div>
                  <label className="text-xs text-white/60">Shop name</label>
                  <input data-testid="input-shop" required value={shopName} onChange={(e) => setShopName(e.target.value)} className="mt-1 w-full px-4 py-3 rounded-xl" placeholder="e.g. Metro Tech Retail" />
                </div>
              </>
            )}
            <div>
              <label className="text-xs text-white/60">Email</label>
              <input data-testid="input-email" required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full px-4 py-3 rounded-xl" />
            </div>
            <div>
              <label className="text-xs text-white/60">Password</label>
              <input data-testid="input-password" required type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full px-4 py-3 rounded-xl" />
            </div>

            <button data-testid="submit-auth" disabled={busy} className="neon-btn w-full py-3 rounded-full flex items-center justify-center gap-2 mt-6">
              {mode === "login" ? <LogIn size={16} /> : <UserPlus size={16} />}
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <div className="my-6 flex items-center gap-3 text-xs text-white/40">
            <div className="flex-1 h-px bg-white/10" /> or <div className="flex-1 h-px bg-white/10" />
          </div>

          <button
            data-testid="btn-google"
            onClick={google}
            className="w-full py-3 rounded-full glass-solid text-sm flex items-center justify-center gap-2 hover:border-white/20 transition-colors"
          >
            <Store size={16} className="text-cyan-400" /> Continue with Google
          </button>

          <p className="text-xs text-white/40 mt-6 text-center">
            Demo owner: <span className="text-cyan-400 font-mono">aneeshthimmapurmath@gmail.com</span> / <span className="font-mono">demo1234</span>
          </p>
        </div>
      </div>
    </div>
  );
}
