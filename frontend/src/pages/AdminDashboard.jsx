import { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from '../contexts/WebSocketContext';
import Timer from '../components/Timer';
import Leaderboard from '../components/Leaderboard';
import './AdminDashboard.css';

const SUB_ROUND_CATEGORIES = {
    1: 'Complex Puzzle',
    2: 'Math',
    3: 'General Knowledge',
};

function getToken() {
    return sessionStorage.getItem('admin_token');
}

function authHeaders() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function AdminDashboard() {
    const { subscribe } = useWebSocket();
    const [authenticated, setAuthenticated] = useState(!!getToken());
    const [password, setPassword] = useState('');
    const [loginError, setLoginError] = useState('');
    const [loginLoading, setLoginLoading] = useState(false);

    const [appState, setAppState] = useState(null);
    const [prompt, setPrompt] = useState('');
    const [timerSeconds, setTimerSeconds] = useState(120);
    const [subRoundDelay, setSubRoundDelay] = useState(30);
    const [roundDelay, setRoundDelay] = useState(300);
    const [timingSettingsSaved, setTimingSettingsSaved] = useState(false);
    const [loading, setLoading] = useState({});
    const [selectedBracketRound, setSelectedBracketRound] = useState(1);
    const [selectedSubRound, setSelectedSubRound] = useState(1);
    const [battleStatus, setBattleStatus] = useState(null);
    const [statusMessage, setStatusMessage] = useState('');
    const [questions, setQuestions] = useState({});

    // ── Login ────────────────────────────────────────────────────
    const handleLogin = async (e) => {
        e.preventDefault();
        setLoginError('');
        setLoginLoading(true);
        try {
            const res = await fetch('/api/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password }),
            });
            const data = await res.json();
            if (!res.ok) {
                setLoginError(data.detail || 'Login failed');
                return;
            }
            sessionStorage.setItem('admin_token', data.token);
            setAuthenticated(true);
        } catch (err) {
            setLoginError('Network error');
        } finally {
            setLoginLoading(false);
        }
    };

    const handleLogout = () => {
        sessionStorage.removeItem('admin_token');
        setAuthenticated(false);
        setAppState(null);
    };

    // ── Fetch state & questions ──────────────────────────────────
    const fetchState = useCallback(async () => {
        try {
            const res = await fetch('/api/admin/state', { headers: authHeaders() });
            if (res.status === 401) { handleLogout(); return; }
            const data = await res.json();
            setAppState(data);
            // Sync timing delays from server state
            if (data.sub_round_delay_seconds !== undefined) setSubRoundDelay(data.sub_round_delay_seconds);
            if (data.round_delay_seconds !== undefined) setRoundDelay(data.round_delay_seconds);
            if (data.current_bracket_round > 0) {
                setSelectedBracketRound(data.current_bracket_round);
            }
            if (data.current_sub_round > 0) {
                setSelectedSubRound(data.current_sub_round);
            }
        } catch (e) {
            console.error(e);
        }
    }, []);

    const fetchQuestions = useCallback(async () => {
        try {
            const res = await fetch('/api/admin/questions', { headers: authHeaders() });
            if (res.ok) {
                const data = await res.json();
                setQuestions(data);
            }
        } catch (e) {
            console.error(e);
        }
    }, []);

    // Auto-fill prompt when round/sub-round changes
    useEffect(() => {
        const q = questions?.[selectedBracketRound]?.[selectedSubRound];
        if (q) setPrompt(q);
        else setPrompt('');
    }, [selectedBracketRound, selectedSubRound, questions]);

    useEffect(() => {
        if (!authenticated) return;
        fetchState();
        fetchQuestions();
        const unsubs = [
            subscribe('*', () => fetchState()),
            subscribe('sub_round_start', (data) => {
                setBattleStatus('running');
                setStatusMessage(`📡 Running ${data.category} across ${data.total_matches} matches...`);
            }),
            subscribe('match_fetched', (data) => {
                setStatusMessage(`📡 Fetched: ${data.team1_name} vs ${data.team2_name}`);
            }),
            subscribe('match_scored', (data) => {
                setStatusMessage(`⚡ ${data.team1_name} (${data.team1_sub_score}) vs ${data.team2_name} (${data.team2_sub_score})`);
            }),
            subscribe('sub_round_complete', (data) => {
                setBattleStatus(null);
                setStatusMessage(`✅ Sub-round ${data.sub_round} complete! (${data.sub_rounds_completed.length}/3 done)`);
            }),
            subscribe('bracket_round_complete', (data) => {
                setBattleStatus(null);
                setStatusMessage(`🏁 Bracket round ${data.bracket_round} complete! Winners advanced.`);
            }),
            subscribe('bracket_update', (data) => {
                if (data.auto_advanced) {
                    setStatusMessage(`🚀 Auto-advanced to bracket round ${data.current_bracket_round}`);
                    setSelectedBracketRound(data.current_bracket_round);
                    setSelectedSubRound(1);
                }
            }),
            subscribe('champion', (data) => {
                setBattleStatus(null);
                setStatusMessage(`🏆 CHAMPION: ${data.team_name}!`);
            }),
        ];
        return () => unsubs.forEach(fn => fn());
    }, [subscribe, fetchState, fetchQuestions, authenticated]);

    const apiCall = async (url, method = 'POST', body = null) => {
        setLoading((prev) => ({ ...prev, [url]: true }));
        try {
            const headers = { ...authHeaders() };
            if (body) headers['Content-Type'] = 'application/json';
            const res = await fetch(url, {
                method,
                headers,
                body: body ? JSON.stringify(body) : null,
            });
            if (res.status === 401) { handleLogout(); return; }

            // Handle non-JSON responses gracefully
            const contentType = res.headers.get('content-type');
            let data;
            if (contentType && contentType.includes('application/json')) {
                data = await res.json();
            } else {
                const text = await res.text();
                throw new Error(text || `Server error: ${res.status}`);
            }

            if (!res.ok) throw new Error(data.detail || 'Error');
            await fetchState();
            return data;
        } catch (e) {
            alert(e.message);
            throw e;
        } finally {
            setLoading((prev) => ({ ...prev, [url]: false }));
        }
    };

    const saveTimingSettings = async () => {
        try {
            await fetch('/api/admin/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    sub_round_delay_seconds: subRoundDelay,
                    round_delay_seconds: roundDelay,
                }),
            });
            setTimingSettingsSaved(true);
            setTimeout(() => setTimingSettingsSaved(false), 2000);
        } catch (e) {
            alert('Failed to save settings: ' + e.message);
        }
    };

    const handleAutoRunMatch = async () => {
        if (!window.confirm(`Auto-run ALL 3 sub-rounds for Bracket Round ${br}?`)) return;
        setBattleStatus('running');
        try {
            for (let sr = 1; sr <= 3; sr++) {
                setSelectedSubRound(sr);
                const q = questions?.[br]?.[sr] || `Prompt for R${br} SR${sr}`;
                setStatusMessage(`Auto-Running SR${sr}...`);
                
                // 1. Set Question
                await apiCall(`/api/admin/bracket-round/${br}/sub-round/${sr}/prompt`, 'POST', { prompt: q, timer_seconds: timerSeconds });
                
                // Let the UI breathe and let the participants see the question
                setStatusMessage(`Waiting for teams to see the prompt...`);
                await new Promise(r => setTimeout(r, 4000));

                // 2. Run Match (this awaits until Gemini judging is complete)
                setStatusMessage(`Auto-Running SR${sr}...`);
                await apiCall(`/api/admin/bracket-round/${br}/sub-round/${sr}/run`, 'POST');
                
                // Wait for UI to settle and give users time to read
                if (sr < 3) await new Promise(r => setTimeout(r, 10000));
            }
            
            setStatusMessage("Advancing Winners...");
            await apiCall(`/api/admin/bracket-round/${br}/complete`, 'POST');
        } catch (e) {
            console.error("Auto-run failed", e);
        } finally {
            setBattleStatus(null);
        }
    };

    // ── Login screen ─────────────────────────────────────────────
    if (!authenticated) {
        return (
            <div className="page-container admin-page">
                <div className="admin-login-gate">
                    <h1 className="page-title">Admin Login</h1>
                    <form onSubmit={handleLogin} className="admin-login-form">
                        <input
                            className="input"
                            type="password"
                            placeholder="Admin password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            autoFocus
                        />
                        <button className="btn btn-primary" type="submit" disabled={loginLoading || !password}>
                            {loginLoading ? 'Logging in...' : 'Login'}
                        </button>
                        {loginError && <p className="login-error">{loginError}</p>}
                    </form>
                </div>
            </div>
        );
    }

    if (!appState) return <div className="page-container"><p>Loading...</p></div>;

    const teams = appState.teams || [];
    const matches = appState.matches || [];
    const br = selectedBracketRound;
    const sr = selectedSubRound;
    const bracketRoundData = appState.bracket_rounds?.[br];
    const totalBracketRounds = appState.total_bracket_rounds || 0;
    const roundMatches = matches
        .filter((m) => m.round_number === br)
        .sort((a, b) => a.match_index - b.match_index);
    const activeTeams = teams.filter((t) => !t.eliminated);

    const subRoundsCompleted = bracketRoundData?.sub_rounds_completed || [];
    const runUrl = `/api/admin/bracket-round/${br}/sub-round/${sr}/run`;
    const promptUrl = `/api/admin/bracket-round/${br}/sub-round/${sr}/prompt`;

    return (
        <div className="page-container admin-page">
            <div className="admin-title-row">
                <h1 className="page-title">Admin Dashboard</h1>
                <button className="btn btn-secondary btn-sm" onClick={handleLogout}>Logout</button>
            </div>
            <p className="page-subtitle">
                🎮 {teams.length} Teams · {totalBracketRounds > 0 ? `${totalBracketRounds} Bracket Rounds` : 'Not started'}
                {appState.champion && ' · 🏆 Champion crowned!'}
            </p>

            {/* Status Banner */}
            {statusMessage && (
                <div className={`battle-status-banner ${battleStatus ? 'active' : 'done'}`}>
                    <span className="status-text">{statusMessage}</span>
                    {battleStatus && <span className="status-spinner"></span>}
                </div>
            )}

            {/* Stats Row */}
            <div className="stats-row">
                <div className="card stat-card">
                    <div className="stat-value">{teams.length}</div>
                    <div className="stat-label">Teams</div>
                </div>
                <div className="card stat-card">
                    <div className="stat-value">{activeTeams.length}</div>
                    <div className="stat-label">Still In</div>
                </div>
                <div className="card stat-card">
                    <div className="stat-value">{roundMatches.length}</div>
                    <div className="stat-label">Matches (R{br})</div>
                </div>
                <div className="card stat-card">
                    <div className="stat-value">{subRoundsCompleted.length}/3</div>
                    <div className="stat-label">Sub-Rounds Done</div>
                </div>
            </div>

            <div className="admin-grid">
                {/* Team Management Card */}
                <div className="card admin-full">
                    <div className="admin-section-header">
                        <h3>👥 Team Management ({teams.length})</h3>
                    </div>
                    {teams.length === 0 ? (
                        <p style={{ color: 'var(--text-muted)' }}>No teams registered yet.</p>
                    ) : (
                        <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                <thead>
                                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', textAlign: 'left' }}>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Name</th>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Members</th>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Endpoint</th>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Seed</th>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Status</th>
                                        <th style={{ padding: '0.5rem', color: 'var(--text-secondary)', textAlign: 'right' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {teams.map((t) => (
                                        <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                                            <td style={{ padding: '0.5rem', fontWeight: 600 }}>{t.name}</td>
                                            <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                                                {Array.isArray(t.members)
                                                    ? t.members.map(m => typeof m === 'string' ? m : m.name).join(', ')
                                                    : '—'}
                                            </td>
                                            <td style={{ padding: '0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {t.endpoint_url || '—'}
                                            </td>
                                            <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                                                {t.seed ? `#${t.seed}` : '—'}
                                            </td>
                                            <td style={{ padding: '0.5rem' }}>
                                                {t.eliminated
                                                    ? <span style={{ color: 'var(--accent-red)', fontSize: '0.8rem' }}>❌ Out</span>
                                                    : <span style={{ color: 'var(--accent-green)', fontSize: '0.8rem' }}>✅ Active</span>}
                                            </td>
                                            <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                                                <button
                                                    className="btn btn-danger btn-sm"
                                                    style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                                                    disabled={appState.bracket_generated || loading[`del-${t.id}`]}
                                                    onClick={async () => {
                                                        if (!window.confirm(`Delete team "${t.name}"? This cannot be undone.`)) return;
                                                        setLoading(prev => ({ ...prev, [`del-${t.id}`]: true }));
                                                        try {
                                                            await apiCall(`/api/admin/teams/${t.id}`, 'DELETE');
                                                        } finally {
                                                            setLoading(prev => ({ ...prev, [`del-${t.id}`]: false }));
                                                        }
                                                    }}
                                                    title={appState.bracket_generated ? 'Cannot delete after bracket is generated' : 'Delete this team'}
                                                >
                                                    🗑️ Delete
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                    {appState.bracket_generated && (
                        <p style={{ fontSize: '0.75rem', color: 'var(--accent-yellow)', marginTop: '0.5rem' }}>
                            ⚠️ Team deletion is disabled after bracket generation. Reset the bracket first to remove teams.
                        </p>
                    )}
                </div>

                {/* Setup Card */}
                <div className="card">
                    <div className="admin-section-header">
                        <h3>⚡ Setup</h3>
                    </div>
                    <div className="admin-controls">
                        <button
                            className="btn btn-secondary"
                            onClick={() => apiCall('/api/admin/seed', 'POST', { mode: 'random' })}
                            disabled={loading['/api/admin/seed'] || teams.length === 0}
                        >
                            {loading['/api/admin/seed'] ? '...' : '🎲 Seed Teams'}
                        </button>
                        <button
                            className="btn btn-primary"
                            onClick={() => apiCall('/api/admin/generate-bracket')}
                            disabled={loading['/api/admin/generate-bracket'] || !appState.seeded}
                        >
                            {loading['/api/admin/generate-bracket'] ? '...' : '📊 Generate Bracket'}
                        </button>
                        <button
                            className="btn btn-secondary"
                            style={{ marginLeft: 'auto', border: '1px solid var(--accent-purple)' }}
                            onClick={() => {
                                if (window.confirm('Reset everything and start dummy match?')) {
                                    apiCall('/api/admin/setup-dummy');
                                }
                            }}
                            disabled={loading['/api/admin/setup-dummy']}
                        >
                            {loading['/api/admin/setup-dummy'] ? '...' : '🤖 Quick Dummy Setup'}
                        </button>
                    </div>
                    <div className="setup-status">
                        {appState.seeded ? '✅ Seeded' : '⏳ Not seeded'}
                        {' · '}
                        {appState.bracket_generated ? `✅ Bracket ready (${totalBracketRounds} rounds)` : '⏳ No bracket'}
                    </div>
                    <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                        <button
                            className={`btn btn-sm ${appState.registration_open ? 'btn-danger' : 'btn-success'}`}
                            onClick={() => apiCall('/api/admin/toggle-registration')}
                            disabled={loading['/api/admin/toggle-registration']}
                        >
                            {appState.registration_open ? '🔒 Close Registration' : '🔓 Open Registration'}
                        </button>
                        <button
                            className={`btn btn-sm ${appState.endpoint_editing_open ? 'btn-danger' : 'btn-success'}`}
                            onClick={() => apiCall('/api/admin/toggle-endpoint-editing')}
                            disabled={loading['/api/admin/toggle-endpoint-editing']}
                        >
                            {appState.endpoint_editing_open ? '🔒 Lock Endpoints' : '🔓 Unlock Endpoints'}
                        </button>
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                        Registration: {appState.registration_open
                            ? <span style={{ color: 'var(--accent-green)' }}>Open</span>
                            : <span style={{ color: 'var(--accent-red)' }}>Closed</span>}
                        {' · '}
                        Endpoints: {appState.endpoint_editing_open
                            ? <span style={{ color: 'var(--accent-green)' }}>Editable</span>
                            : <span style={{ color: 'var(--accent-red)' }}>Locked</span>}
                    </div>
                </div>

                {/* Timing Settings Card */}
                <div className="card">
                    <div className="admin-section-header">
                        <h3>⏱ Timing Settings</h3>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', minWidth: '160px' }}>
                                Sub-Round Break (s)
                            </label>
                            <input
                                className="input timer-input"
                                type="number"
                                value={subRoundDelay}
                                onChange={(e) => setSubRoundDelay(Number(e.target.value))}
                                min={0}
                                max={600}
                                style={{ width: '80px' }}
                            />
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', minWidth: '160px' }}>
                                Round Break (s)
                            </label>
                            <input
                                className="input timer-input"
                                type="number"
                                value={roundDelay}
                                onChange={(e) => setRoundDelay(Number(e.target.value))}
                                min={0}
                                max={3600}
                                style={{ width: '80px' }}
                            />
                        </div>
                        <button
                            className="btn btn-primary btn-sm"
                            onClick={saveTimingSettings}
                            style={{ alignSelf: 'flex-start' }}
                        >
                            {timingSettingsSaved ? '✅ Saved!' : '💾 Save Timing'}
                        </button>
                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0 }}>
                            Delays fire automatically as countdown timers visible to all participants.
                        </p>
                    </div>
                </div>

                {/* Bracket Round Selector + Sub-Round */}
                <div className="card">
                    <div className="admin-section-header">
                        <h3>📋 Round & Sub-Round</h3>
                    </div>
                    {/* Bracket round selector */}
                    <div className="bracket-round-selector">
                        {Array.from({ length: totalBracketRounds }, (_, i) => i + 1).map((r) => {
                            const brData = appState.bracket_rounds?.[r];
                            return (
                                <button
                                    key={r}
                                    className={`bracket-round-btn ${br === r ? 'active' : ''} ${brData?.completed ? 'completed' : ''}`}
                                    onClick={() => { setSelectedBracketRound(r); setSelectedSubRound(1); }}
                                >
                                    R{r}
                                    {brData?.completed && <span className="mini-check">✓</span>}
                                    {brData?.active && !brData?.completed && <span className="mini-live">●</span>}
                                </button>
                            );
                        })}
                    </div>
                    {/* Sub-round tabs */}
                    <div className="sub-round-tabs">
                        {[1, 2, 3].map((s) => (
                            <button
                                key={s}
                                className={`sub-round-tab ${sr === s ? 'active' : ''} ${subRoundsCompleted.includes(s) ? 'completed' : ''}`}
                                onClick={() => setSelectedSubRound(s)}
                            >
                                <span className="sr-number">SR{s}</span>
                                <span className="sr-category">{SUB_ROUND_CATEGORIES[s]}</span>
                                {subRoundsCompleted.includes(s) && <span className="sr-check">✅</span>}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Sub-Round Config + Run */}
                <div className="card">
                    <div className="admin-section-header">
                        <h3>🧪 SR{sr}: {SUB_ROUND_CATEGORIES[sr]}</h3>
                        <span className={`badge ${subRoundsCompleted.includes(sr) ? 'badge-green' : 'badge-cyan'}`}>
                            {subRoundsCompleted.includes(sr) ? 'DONE' : 'PENDING'}
                        </span>
                    </div>
                    <div className="prompt-editor">
                        <textarea
                            className="input"
                            placeholder={`Enter the ${SUB_ROUND_CATEGORIES[sr]} question...`}
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            rows={3}
                        />
                        <div className="timer-controls">
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 0 }}>Timer (s):</label>
                            <input
                                className="input timer-input"
                                type="number"
                                value={timerSeconds}
                                onChange={(e) => setTimerSeconds(Number(e.target.value))}
                                min={10}
                                max={3600}
                            />
                            <button
                                className="btn btn-primary btn-sm"
                                onClick={() => apiCall(promptUrl, 'POST', { prompt, timer_seconds: timerSeconds })}
                                disabled={!prompt.trim() || !appState.bracket_generated}
                            >
                                Set Question
                            </button>
                        </div>
                    </div>
                </div>

                {/* Battle Controls */}
                <div className="card">
                    <div className="admin-section-header">
                        <h3>⚔️ Battle Controls</h3>
                    </div>
                    <Timer />
                    <div className="battle-controls" style={{ marginTop: '1rem' }}>
                        <button
                            className="btn btn-success btn-sm"
                            onClick={() => apiCall('/api/admin/timer/start', 'POST', { timer_seconds: timerSeconds })}
                            disabled={!appState.bracket_generated}
                        >
                            ▶ Start Timer
                        </button>
                        <button
                            className="btn btn-danger btn-sm"
                            onClick={() => apiCall('/api/admin/timer/stop')}
                        >
                            ⏹ Stop
                        </button>
                        <button
                            className="btn btn-primary"
                            onClick={() => {
                                setBattleStatus('running');
                                apiCall(runUrl).finally(() => setBattleStatus(null));
                            }}
                            disabled={loading[runUrl] || battleStatus === 'running' || subRoundsCompleted.includes(sr)}
                        >
                            {battleStatus === 'running' ? '⚔️ Running...' : `⚔️ Run SR${sr}: ${SUB_ROUND_CATEGORIES[sr]}`}
                        </button>
                    </div>
                    
                    <div style={{ marginTop: '1.5rem', background: 'rgba(255, 68, 68, 0.05)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--accent-red)' }}>
                        <h4 style={{ color: 'var(--accent-red)', marginBottom: '0.5rem', marginTop: 0 }}>🚨 Advanced Controls</h4>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                            Auto-Pilot runs all 3 sub-rounds sequentially. Restart deletes all current round history to try again.
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                            <button
                                className="btn"
                                style={{ background: 'var(--accent-red)', color: 'white', width: '100%', fontWeight: 'bold' }}
                                onClick={handleAutoRunMatch}
                                disabled={battleStatus === 'running' || subRoundsCompleted.length > 0}
                            >
                                ▶️ AUTO-RUN ENTIRE BRACKET ROUND {br}
                            </button>
                            <button
                                className="btn btn-secondary"
                                style={{ border: '1px dashed var(--accent-red)', color: 'var(--text-primary)', width: '100%', opacity: battleStatus === 'running' ? 0.5 : 1 }}
                                onClick={() => {
                                    if(window.confirm(`Are you SURE you want to RESET Bracket Round ${br}? All submissions and scores for this round will be instantly deleted.`)) {
                                        apiCall(`/api/admin/bracket-round/${br}/reset`, 'POST');
                                    }
                                }}
                                disabled={battleStatus === 'running'}
                            >
                                🔄 RESTART BRACKET ROUND {br}
                            </button>
                        </div>
                    </div>
                    <p className="flow-hint">
                        Set question → Run (fetches + judges ALL matches concurrently) → After 3 sub-rounds, winners auto-advance
                    </p>
                    {subRoundsCompleted.length >= 3 && !bracketRoundData?.completed && (
                        <button
                            className="btn btn-success"
                            style={{ marginTop: '0.75rem', width: '100%' }}
                            onClick={() => apiCall(`/api/admin/bracket-round/${br}/complete`)}
                        >
                            🏁 Complete Round & Advance Winners
                        </button>
                    )}
                </div>

                {/* Champion + Reset */}
                {appState.champion && (
                    <div className="card admin-full">
                        <div className="champion-card">
                            <span className="champion-trophy">🏆</span>
                            <div className="champion-name">
                                {teams.find((t) => t.id === appState.champion)?.name || 'Champion!'}
                            </div>
                            <div className="champion-score">
                                Total Score: {teams.find((t) => t.id === appState.champion)?.total_score || 0}
                            </div>
                        </div>
                    </div>
                )}

                {/* Match Results Table */}
                <div className="card admin-full">
                    <div className="admin-section-header">
                        <h3>📊 Bracket Round {br} — Matches ({roundMatches.length})</h3>
                        <button
                            className="btn btn-danger btn-sm"
                            onClick={() => { if (window.confirm('Reset all data?')) apiCall('/api/admin/reset'); }}
                        >
                            ♻️ Reset
                        </button>
                    </div>
                    {roundMatches.length === 0 ? (
                        <p style={{ color: 'var(--text-muted)' }}>No matches yet. Generate the bracket first.</p>
                    ) : (
                        <div className="match-grid">
                            {roundMatches.map((match) => (
                                <MatchCard key={match.id} match={match} submissions={appState.submissions || []} />
                            ))}
                        </div>
                    )}
                </div>

                {/* Leaderboard */}
                <div className="card admin-full">
                    <div className="admin-section-header">
                        <h3>🏅 Standings</h3>
                    </div>
                    <Leaderboard />
                </div>
            </div>
        </div>
    );
}

function MatchCard({ match, submissions }) {
    const isBye = !(match.team1_id && match.team2_id);
    const matchSubs = submissions.filter((s) => s.match_id === match.id);

    // Get sub-round scores
    const getSubScore = (teamId, subRound) => {
        const sub = matchSubs.find((s) => s.team_id === teamId && s.sub_round === subRound);
        return sub?.score;
    };

    return (
        <div className={`match-card ${match.completed ? 'completed' : ''} ${isBye ? 'bye' : ''}`}>
            <div className="match-header">
                <span className="match-index">M{match.match_index + 1}</span>
                {match.completed && match.winner_name && (
                    <span className="match-winner-tag">👑 {match.winner_name}</span>
                )}
                {isBye && <span className="badge badge-purple">BYE</span>}
            </div>

            <div className="match-teams">
                {/* Team 1 */}
                <div className={`match-team ${match.winner_id === match.team1_id ? 'winner' : ''}`}>
                    <div className="match-team-name">
                        {match.team1_seed && <span className="seed-tag">#{match.team1_seed}</span>}
                        {match.team1_name || '—'}
                    </div>
                    <div className="match-sub-scores">
                        {[1, 2, 3].map((sr) => {
                            const score = getSubScore(match.team1_id, sr);
                            return (
                                <span key={sr} className={`sub-score ${score != null ? 'scored' : ''}`} title={SUB_ROUND_CATEGORIES[sr]}>
                                    {score != null ? score : '·'}
                                </span>
                            );
                        })}
                    </div>
                    <div className="match-team-total">{match.team1_total || 0}</div>
                </div>

                <div className="vs-divider">VS</div>

                {/* Team 2 */}
                <div className={`match-team ${match.winner_id === match.team2_id ? 'winner' : ''}`}>
                    <div className="match-team-name">
                        {match.team2_seed && <span className="seed-tag">#{match.team2_seed}</span>}
                        {match.team2_name || '—'}
                    </div>
                    <div className="match-sub-scores">
                        {[1, 2, 3].map((sr) => {
                            const score = getSubScore(match.team2_id, sr);
                            return (
                                <span key={sr} className={`sub-score ${score != null ? 'scored' : ''}`} title={SUB_ROUND_CATEGORIES[sr]}>
                                    {score != null ? score : '·'}
                                </span>
                            );
                        })}
                    </div>
                    <div className="match-team-total">{match.team2_total || 0}</div>
                </div>
            </div>
        </div>
    );
}
