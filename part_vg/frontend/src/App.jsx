import { BifrostProvider } from "./BifrostContext.jsx";
import Analytics from "./components/Analytics.jsx";
import MainHub from "./components/MainHub.jsx";
import Sidebar from "./components/Sidebar.jsx";

export default function App() {
  return (
    <BifrostProvider>
      <div className="grid h-screen min-h-0 grid-cols-1 grid-rows-[auto_1fr_auto] gap-3 bg-midgard p-3 text-slate-100 lg:grid-cols-[280px_1fr_320px] lg:grid-rows-1">
        <div className="min-h-0 max-h-[40vh] overflow-hidden lg:max-h-none">
          <Sidebar />
        </div>
        <div className="min-h-0 min-w-0 overflow-hidden">
          <MainHub />
        </div>
        <div className="min-h-0 max-h-[45vh] overflow-hidden lg:max-h-none">
          <Analytics />
        </div>
      </div>
    </BifrostProvider>
  );
}
