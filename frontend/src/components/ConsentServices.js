import { useEffect } from "react";
import { clearOptionalStorage, useConsent } from "@/lib/cookieConsent";

const FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&family=Archivo:wght@400;500;600;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap";

export default function ConsentServices() {
  const consent = useConsent();
  useEffect(() => {
    if (!consent?.preferences) clearOptionalStorage();
  }, [consent?.preferences]);
  useEffect(() => {
    if (!consent?.fonts) return;
    const link = document.createElement("link");
    link.id = "roster-google-fonts"; link.rel = "stylesheet"; link.href = FONT_URL;
    document.head.appendChild(link);
    return () => link.remove();
  }, [consent?.fonts]);
  useEffect(() => {
    // Removing a script cannot stop code already executed; reload to end Google's runtime.
    if (!consent?.google && document.querySelector('script[src="https://accounts.google.com/gsi/client"]')) {
      window.location.reload();
    }
  }, [consent?.google]);
  return null;
}
