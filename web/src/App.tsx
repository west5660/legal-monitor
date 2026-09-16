import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import DashboardPage from "./pages/Dashboard";
import DocumentsPage from "./pages/Documents";
import ExportsPage from "./pages/Exports";
import PipelinePage from "./pages/Pipeline";
import ProfilesPage from "./pages/Profiles";
import ActivityPage from "./pages/Activity";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="exports" element={<ExportsPage />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="profiles" element={<ProfilesPage />} />
        <Route path="activity" element={<ActivityPage />} />
      </Route>
    </Routes>
  );
}
