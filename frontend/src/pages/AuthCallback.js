import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const hash = location.hash || window.location.hash;
    const match = hash.match(/session_id=([^&]+)/);
    const sid = match?.[1];
    if (!sid) { navigate("/login", { replace: true }); return; }
    (async () => {
      try {
        await api.post("/auth/google/session", { session_id: sid });
        window.history.replaceState({}, "", "/");
        await refresh();
        navigate("/", { replace: true });
      } catch (e) {
        navigate("/login", { replace: true });
      }
    })();
  }, [location, navigate, refresh]);

  return (
    <div className="min-h-screen flex items-center justify-center text-white/60">
      Signing you in…
    </div>
  );
}
