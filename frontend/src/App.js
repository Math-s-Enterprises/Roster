import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";

import "@/App.css";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import AppLayout from "@/components/AppLayout";
import Login from "@/pages/Login";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import Onboarding from "@/pages/Onboarding";
import Employees from "@/pages/Employees";
import CalendarPage from "@/pages/CalendarPage";
import FixedShifts from "@/pages/FixedShifts";
import AIRules from "@/pages/AIRules";
import RosterView from "@/pages/RosterView";
import PastRosters from "@/pages/PastRosters";
import ImportRosters from "@/pages/ImportRosters";
import SickReport from "@/pages/SickReport";
import HoursReport from "@/pages/HoursReport";
import Pricing from "@/pages/Pricing";
import { PaymentCancel, PaymentSuccess } from "@/pages/PaymentResult";

/**
 * Gate for authenticated pages.
 *
 * The `loading` check matters: on a fresh page load `user` is null until
 * /auth/me resolves. Redirecting on null alone would bounce a signed-in user
 * to the login screen on every refresh.
 */
function Protected({ children }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-white/60">
        Loading…
      </div>
    );
  }
  return user ? children : <Navigate to="/login" replace />;
}

/** Keeps signed-in users away from the login page. */
function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnly>
                <Login />
              </PublicOnly>
            }
          />
          <Route
            path="/forgot-password"
            element={
              <PublicOnly>
                <ForgotPassword />
              </PublicOnly>
            }
          />
          <Route
            path="/reset-password"
            element={
              <PublicOnly>
                <ResetPassword />
              </PublicOnly>
            }
          />
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
            <Route path="import" element={<ImportRosters />} />
            <Route path="sick-report" element={<SickReport />} />
            <Route path="reports/hours" element={<HoursReport />} />
            <Route path="pricing" element={<Pricing />} />
            <Route path="payment/success" element={<PaymentSuccess />} />
            <Route path="payment/cancel" element={<PaymentCancel />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster theme="dark" position="top-right" richColors />
      </BrowserRouter>
    </AuthProvider>
  );
}
