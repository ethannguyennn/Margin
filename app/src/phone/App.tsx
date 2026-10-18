import { Route, Routes, useLocation } from 'react-router-dom';
import { RelayStatus } from './components/RelayStatus';
import { TabBar } from './components/TabBar';
import { ThemeToggle } from './components/ThemeToggle';
import AnswerPage from './pages/AnswerPage';
import LensPage from './pages/LensPage';
import SopsPage from './pages/SopsPage';

const HEADS: Record<string, { title: string; subtitle: string }> = {
  '/': { title: 'Answer', subtitle: 'Full text, citations and walkthrough' },
  '/lens': { title: 'Lens', subtitle: 'Session and input for the glasses' },
  '/sops': { title: 'SOPs', subtitle: 'Procedures and deviations' },
};

export default function App() {
  const { pathname } = useLocation();
  const head = HEADS[pathname] ?? { title: 'Specs', subtitle: 'Phone display' };

  return (
    <div className="shell">
      <div className="app">
        <header className="app-header">
          <div className="head-text">
            <p className="eyebrow">Specs</p>
            <h1>{head.title}</h1>
            <p className="subtitle">{head.subtitle}</p>
          </div>
          <div className="head-actions">
            <RelayStatus />
            <ThemeToggle />
          </div>
        </header>

        <main className="app-main">
          <Routes>
            <Route path="/" element={<AnswerPage />} />
            <Route path="/lens" element={<LensPage />} />
            <Route path="/sops" element={<SopsPage />} />
            <Route
              path="*"
              element={
                <section className="card">
                  <h2 className="section-title">No such screen</h2>
                  <p className="body">Use the tabs below to reach Answer, Lens or SOPs.</p>
                </section>
              }
            />
          </Routes>
        </main>

        <TabBar />
      </div>
    </div>
  );
}
