import { BifrostProvider } from "./BifrostContext.jsx";
import Analytics from "./components/Analytics.jsx";
import MainHub from "./components/MainHub.jsx";
import Sidebar from "./components/Sidebar.jsx";

export default function App() {
  return (
    <BifrostProvider>
      <div className="grid h-screen grid-cols-[300px_1fr_340px] gap-3 bg-midgard p-3 text-slate-100">
        <Sidebar />
        <MainHub />
        <Analytics />
      </div>
    </BifrostProvider>
  );
}
