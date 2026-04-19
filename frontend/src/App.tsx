import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { GoogleAnalyticsListener } from "./components/GoogleAnalyticsListener";
import { Shell } from "./layout/Shell";
import { AbsoluteVotesForm } from "./pages/AbsoluteVotesForm";
import { Landing } from "./pages/Landing";
import { Calculator } from "./pages/Calculator";

export default function App() {
  return (
    <BrowserRouter>
      <GoogleAnalyticsListener />
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Landing />} />
          <Route path="/app/votes" element={<AbsoluteVotesForm />} />
          <Route path="/app" element={<Calculator />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
