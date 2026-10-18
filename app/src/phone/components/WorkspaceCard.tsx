import { useEffect, useState } from 'react';
import { joinWorkspace, pairingStatus, RelayError } from '../../api/client';
import { getDevice } from '../../settings';
import type { Pairing } from '../../types';
import { toast } from '../toast';

/**
 * Join the admin's workspace: the worker types the code the admin portal shows, and the
 * glasses answer from that workspace's SOPs. The lens leaves its JOIN screen on its own
 * (it polls the relay until the device is claimed).
 */
export function WorkspaceCard() {
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!getDevice()) return;
    let live = true;
    pairingStatus().then((p) => { if (live) setPairing(p); }).catch(() => {});
    return () => { live = false; };
  }, []);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const joined = await joinWorkspace(code, name);
      setPairing(joined);
      setEditing(false);
      setCode('');
      toast(`Joined ${joined.workspace ?? 'workspace'}`);
    } catch (e) {
      setError(e instanceof RelayError && e.code === 'not_found'
        ? 'No workspace has that code. Check the code in the admin portal.'
        : 'Could not reach the server. Try again.');
    } finally {
      setBusy(false);
    }
  };

  if (pairing?.claimed && !editing) {
    return (
      <section className="group">
        <h2 className="group-title">Workspace</h2>
        <div className="group-body">
          <div className="group-row">
            <span className="label">Workspace</span>
            <span className="value">{pairing.workspace ?? 'Joined'}</span>
          </div>
          <div className="group-row">
            <span className="label">Worker</span>
            <span className="value">{pairing.worker_name ?? '—'}</span>
          </div>
          <button className="group-row group-action" onClick={() => { setName(pairing.worker_name ?? ''); setEditing(true); }}>
            Change workspace
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 className="section-title">Join a workspace</h2>
      <p className="meta">Enter the code from your admin portal. Your glasses then answer from that team's SOPs.</p>
      <label className="field">
        <span>Workspace code</span>
        <input
          className="input mono"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          placeholder="K7P2QX"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
        />
      </label>
      <label className="field">
        <span>Your name</span>
        <input className="input" placeholder="Maria, Line 3" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="row wrap">
        <button className="primary" aria-busy={busy} disabled={busy || !code.trim()} onClick={() => void submit()}>
          {busy ? 'Joining…' : 'Join'}
        </button>
        {editing && <button className="ghost" onClick={() => setEditing(false)}>Cancel</button>}
      </div>
      {error && <p className="error-line">{error}</p>}
    </section>
  );
}
