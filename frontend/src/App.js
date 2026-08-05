import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import Onboarding from "@/pages/Onboarding";
import Employees from "@/pages/Employees";
import CalendarPage from "@/pages/CalendarPage";
import FixedShifts from "@/pages/FixedShifts";
import AIRules from "@/pages/AIRules";
import RosterView from "@/pages/RosterView";
import PastRosters from "@/pages/PastRosters";
import Pricing from "@/pages/Pricing";
import { PaymentSuccess, PaymentCancel } from "@/pages/PaymentResult";
import AppLayout from "@/components/AppLayout";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-white/60">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function Router() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="onboarding" element={<Onboarding />} />
        <Route path="employees" element={<Employees />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="fixed-shifts" element={<FixedShifts />} />
        <Route path="rules" element={<AIRules />} />
        <Route path="roster" element={<RosterView />} />
        <Route path="past" element={<PastRosters />} />
        <Route path="pricing" element={<Pricing />} />
        <Route path="payment/success" element={<PaymentSuccess />} />
        <Route path="payment/cancel" element={<PaymentCancel />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Router />
        <Toaster theme="dark" position="top-right" richColors />
      </BrowserRouter>
    </AuthProvider>
  );
}
