import React, { useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import confetti from "canvas-confetti";

export function PaymentSuccess() {
  const [params] = useSearchParams();
  const sessionId = params.get("session_id");
  const [status, setStatus] = useState("polling");
  const [tries, setTries] = useState(0);
  const { refresh } = useAuth();
  const done = useRef(false);

  useEffect(() => {
    if (!sessionId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const r = await api.get(`/payments/status/${sessionId}`);
        if (r.data.payment_status === "paid") {
          if (done.current) return;
          done.current = true;
          setStatus("paid");
          confetti({ particleCount: 200, spread: 100, origin: { y: 0.5 }, colors: ["#00E5FF", "#7C4DFF", "#ffffff"] });
          await refresh();
          return;
        }
        if (r.data.status === "expired" || r.data.status === "failed") { setStatus("failed"); return; }
      } catch {}
      setTries((t) => t + 1);
      if (!stopped) setTimeout(poll, 2000);
    };
    poll();
    return () => { stopped = true; };
  }, [sessionId, refresh]);

  if (tries > 15 && status === "polling") {
    return <Wrap><XCircle size={40} className="text-amber-400" /><h2 className="text-2xl font-light mt-4">Still processing…</h2><p className="text-white/60 text-sm">This can take a minute. Refresh in a moment.</p></Wrap>;
  }
  if (status === "failed") {
    return <Wrap><XCircle size={40} className="text-red-400" /><h2 className="text-2xl font-light mt-4">Payment failed</h2><Link to="/pricing" className="mt-6 neon-btn px-5 py-2.5 rounded-full text-sm">Try again</Link></Wrap>;
  }
  if (status === "paid") {
    return <Wrap><CheckCircle2 size={40} className="text-emerald-400" /><h2 className="text-2xl font-light mt-4">You're now on <span className="neon-text font-medium">Pro</span></h2><Link to="/" className="mt-6 neon-btn px-5 py-2.5 rounded-full text-sm">Back to dashboard</Link></Wrap>;
  }
  return <Wrap><Loader2 size={40} className="text-cyan-400 animate-spin" /><h2 className="text-2xl font-light mt-4">Confirming payment…</h2></Wrap>;
}

export function PaymentCancel() {
  return <Wrap><XCircle size={40} className="text-white/50" /><h2 className="text-2xl font-light mt-4">Checkout canceled</h2><Link to="/pricing" className="mt-6 neon-btn px-5 py-2.5 rounded-full text-sm">Back to pricing</Link></Wrap>;
}

const Wrap = ({ children }) => (
  <div className="min-h-[70vh] flex items-center justify-center">
    <div className="glass rounded-3xl p-12 max-w-md text-center flex flex-col items-center">{children}</div>
  </div>
);
