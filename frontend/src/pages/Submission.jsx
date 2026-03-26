import { useState, useEffect, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import Timer from '../components/Timer';
import './Submission.css';

const SUB_ROUND_CATEGORIES = {
    1: 'Complex Puzzle',
    2: 'Math',
    3: 'General Knowledge',
};

export default function Submission() {
    const { subscribe } = useWebSocket();
    const location = useLocation();
    const navigate = useNavigate();

    // Load team from location.state first, then fall back to localStorage
    const [team, setTeam] = useState(() => {
        if (location.state?.team) {
            // Also persist to localStorage when coming from registration
            localStorage.setItem('team', JSON.stringify(location.state.team));
            return location.state.team;
        }
        // Try to restore from localStorage (handles refresh/tab switch)
        const stored = localStorage.getItem('team');
        if (stored) {
            try {
                return JSON.parse(stored);
            } catch {
                localStorage.removeItem('team');
            }
        }
        return null;
    });
    const [teamNameInput, setTeamNameInput] = useState('');
    const [passwordInput, setPasswordInput] = useState('');
    const [loginError, setLoginError] = useState('');
    const [appData, setAppData] = useState(null);
    const [endpointStatus, setEndpointStatus] = useState(null);
    const [testingEndpoint, setTestingEndpoint] = useState(false);
    const [matchUpdates, setMatchUpdates] = useState({});
    const [editingEndpoint, setEditingEndpoint] = useState(false);
    const [newEndpointUrl, setNewEndpointUrl] = useState('');
    const [savingEndpoint, setSavingEndpoint] = useState(false);

    const fetchTeamData = async () => {
        if (!team?.id) return;
        try {
            const teamRes = await fetch(`/api/teams/${team?.id}`);
            if (teamRes.ok) {
                const updatedTeam = await teamRes.json();
                setTeam(updatedTeam);
                // Keep localStorage in sync
                localStorage.setItem('team', JSON.stringify(updatedTeam));
            }
            const stateRes = await fetch('/api/state');
            setAppData(await stateRes.json());
        } catch (e) { console.error(e); }
    };

    useEffect(() => {
        const unsubs = [
            subscribe('match_scored', () => fetchTeamData()),
            subscribe('bracket_round_complete', () => fetchTeamData()),
            subscribe('bracket_update', () => fetchTeamData()),
            subscribe('match_result', () => fetchTeamData()),
            subscribe('match_update', (data) => {
                if (!team?.id) return;
                const d = data.data || data;
                // Only track updates relevant to this team
                if (d.team1_id === team?.id || d.team2_id === team?.id) {
                    setMatchUpdates(prev => ({
                        ...prev,
                        [`${d.match_id}_${d.sub_round}`]: d,
                    }));
                }
            }),
        ];
        return () => unsubs.forEach(fn => fn());
    }, [subscribe, team]);

    useEffect(() => { if (team) fetchTeamData(); }, [team?.id]);

    const handleLogin = async (e) => {
        e.preventDefault();
        setLoginError('');
        try {
            const res = await fetch('/api/teams/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: teamNameInput.trim(),
                    password: passwordInput.trim()
                }),
            });
            if (!res.ok) {
                const d = await res.json();
                throw new Error(d.detail || 'Login failed');
            }
            const teamData = await res.json();
            // Persist login to localStorage
            localStorage.setItem('team', JSON.stringify(teamData));
            setTeam(teamData);
            window.location.reload()
        } catch (e) { setLoginError(e.message); }
    };

    const handleLogout = () => {
        localStorage.removeItem('team');
        localStorage.clear();
        setTeam(null);
        navigate("/submit");
        window.location.reload();
    };

    const testEndpoint = async () => {
        if (!team?.endpoint_url) return;
        setTestingEndpoint(true);
        try {
            const res = await fetch('/api/teams/test-endpoint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: team?.endpoint_url }),
            });
            setEndpointStatus(await res.json());
        } catch (e) { setEndpointStatus({ success: false, error: e.message }); }
        finally { setTestingEndpoint(false); }
    };

    const handleEditEndpoint = () => {
        setNewEndpointUrl(team?.endpoint_url || '');
        setEditingEndpoint(true);
        setEndpointStatus(null);
    };

    const handleSaveEndpoint = async () => {
        if (!newEndpointUrl.trim()) return;
        if (newEndpointUrl.trim() !== 'DUMMY' && !newEndpointUrl.trim().endsWith('.modal.run')) {
            setEndpointStatus({ success: false, error: 'Endpoint URL must end with .modal.run' });
            return;
        }
        setSavingEndpoint(true);
        try {
            const res = await fetch(`/api/teams/${team.id}/endpoint`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ endpoint_url: newEndpointUrl.trim() }),
            });
            if (!res.ok) {
                const d = await res.json();
                throw new Error(d.detail || 'Failed to update endpoint');
            }
            const updatedTeam = await res.json();
            setTeam(updatedTeam);
            localStorage.setItem('team', JSON.stringify(updatedTeam));
            setEditingEndpoint(false);
        } catch (e) {
            setEndpointStatus({ success: false, error: e.message });
        } finally {
            setSavingEndpoint(false);
        }
    };

    if (!team) {
        return (
            <div className="page-container submission-page">
                <h1 className="page-title">Team Status</h1>
                <p className="page-subtitle">Log in to view your team's match progress</p>
                <div className="card login-card animate-in">
                    <form onSubmit={handleLogin}>
                        <div className="form-group">
                            <label>Team Name</label>
                            <input className="input" type="text" placeholder="Enter your team name" value={teamNameInput} onChange={(e) => setTeamNameInput(e.target.value)} required />
                        </div>
                        <div className="form-group">
                            <label>Password</label>
                            <input className="input" type="password" placeholder="Enter your password" value={passwordInput} onChange={(e) => setPasswordInput(e.target.value)} required />
                        </div>
                        {loginError && <p style={{ color: 'var(--accent-red)', marginBottom: '1rem', fontSize: '0.9rem' }}>{loginError}</p>}
                        <button className="btn btn-primary" type="submit">Log In</button>
                    </form>
                </div>
            </div>
        );
    }

    const matches = (appData?.matches || []).filter(m => m.team1_id === team?.id || m.team2_id === team?.id);
    const submissions = (appData?.submissions || []).filter(s => s.team_id === team?.id);

    // Find current active match (not completed)
    const activeMatch = matches.find(m => !m.completed);
    
    // Auto-join battle when it starts, unless explicitly backed out
    useEffect(() => {
        if (activeMatch && !location.state?.fromBattle) {
            navigate('/battle', { state: { team } });
        }
    }, [activeMatch, team, navigate, location.state]);

    // Get live updates for the active match
    const liveUpdates = activeMatch
        ? [1, 2, 3].map(sr => matchUpdates[`${activeMatch.id}_${sr}`]).filter(Boolean)
        : [];

    // Helper to personalize data (your vs opponent)
    const personalize = (update) => {
        const isTeam1 = update.team1_id === team?.id;
        return {
            yourResponse: isTeam1 ? update.team1_response : update.team2_response,
            opponentResponse: isTeam1 ? update.team2_response : update.team1_response,
            yourScore: isTeam1 ? update.team1_score : update.team2_score,
            opponentScore: isTeam1 ? update.team2_score : update.team1_score,
            yourTotal: isTeam1 ? update.team1_total : update.team2_total,
            opponentTotal: isTeam1 ? update.team2_total : update.team1_total,
            opponentName: isTeam1 ? update.team2_name : update.team1_name,
        };
    };

    return (
        <div className="page-container submission-page">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h1 className="page-title">Team Status</h1>
                    <p className="page-subtitle">
                        <strong style={{ color: 'var(--accent-cyan)' }}>{team?.name || 'Loading...'}</strong>
                        {team?.seed && <span style={{ color: 'var(--text-muted)', marginLeft: '0.5rem' }}>Seed #{team.seed}</span>}
                        {team?.eliminated && <span className="badge badge-red" style={{ marginLeft: '0.75rem' }}>ELIMINATED</span>}
                    </p>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                    Logout
                </button>
            </div>

            <Timer />

            {/* Endpoint */}
            <div className="card team-info-card animate-in" style={{ marginTop: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ color: 'var(--accent-cyan)', fontSize: '1rem', fontWeight: 700 }}>📡 Endpoint</h3>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {!editingEndpoint && (
                            <button className="btn btn-secondary btn-sm" onClick={handleEditEndpoint}>
                                ✏️ Edit
                            </button>
                        )}
                        <button className="btn btn-secondary btn-sm" onClick={testEndpoint} disabled={testingEndpoint || editingEndpoint}>
                            {testingEndpoint ? '🔄 Testing...' : '🧪 Test'}
                        </button>
                    </div>
                </div>
                {editingEndpoint ? (
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <input
                            className="input"
                            type="url"
                            value={newEndpointUrl}
                            onChange={(e) => setNewEndpointUrl(e.target.value)}
                            placeholder="https://your-llm-endpoint.com/generate"
                            style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}
                        />
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => { setNewEndpointUrl('DUMMY'); }}
                            title="Use dummy endpoint"
                        >
                            🤖
                        </button>
                        <button
                            className="btn btn-primary btn-sm"
                            onClick={handleSaveEndpoint}
                            disabled={savingEndpoint || !newEndpointUrl.trim()}
                        >
                            {savingEndpoint ? 'Saving...' : 'Save'}
                        </button>
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => setEditingEndpoint(false)}
                        >
                            Cancel
                        </button>
                    </div>
                ) : (
                    <div className="endpoint-url">{team?.endpoint_url || 'No endpoint configured'}</div>
                )}
                {endpointStatus && (
                    <div className={`endpoint-result ${endpointStatus.success ? 'success' : 'error'}`}>
                        {endpointStatus.success
                            ? `✅ Responding! Got: "${(endpointStatus.response || '').slice(0, 100)}" in ${endpointStatus.latency_ms}ms`
                            : `❌ ${endpointStatus.error}`
                        }
                    </div>
                )}
                <div className="team-meta">
                    <span>Members: {team?.members?.map((m, i) => (
                        <span key={i}>{m.name} ({m.roll}){i < team.members.length - 1 ? ', ' : ''}</span>
                    )) || 'No members listed'}</span>
                    <span>Total Score: <strong style={{ color: 'var(--accent-green)', fontFamily: 'var(--font-mono)' }}>{team?.total_score || 0}</strong></span>
                </div>
            </div>

            {/* Live Battle View */}
            {activeMatch && liveUpdates.length > 0 && (
                <div style={{ marginTop: '2rem' }}>
                    <div className="card text-center animate-in" style={{ padding: '3rem', border: '2px solid var(--accent-cyan)', background: 'linear-gradient(rgba(0,255,255,0.05), rgba(0,255,136,0.05))', boxShadow: '0 0 30px rgba(0,255,255,0.1)' }}>
                        <h2 style={{ fontSize: '2.5rem', marginBottom: '1rem', color: 'var(--accent-cyan)', textTransform: 'uppercase', letterSpacing: '2px' }}>
                            ⚔️ MATCH IN PROGRESS
                        </h2>
                        <p style={{ marginBottom: '2rem', fontSize: '1.2rem', color: 'var(--text-secondary)' }}>
                            You are currently battling <strong style={{ color: 'var(--accent-red)' }}>{activeMatch.team1_id === team?.id ? activeMatch.team2_name : activeMatch.team1_name}</strong>.
                        </p>
                        <button 
                            className="btn btn-primary" 
                            onClick={() => navigate('/battle', { state: { team } })} 
                            style={{ fontSize: '1.5rem', padding: '1.2rem 4rem', fontWeight: 800, letterSpacing: '2px', boxShadow: '0 0 20px rgba(0, 255, 136, 0.4)' }}
                        >
                            ENTER BATTLE ARENA
                        </button>
                    </div>
                </div>
            )}

            {/* Match History */}
            <div style={{ marginTop: '2rem' }}>
                <h2 className="section-title">Your Matches</h2>
                <div className="rounds-grid">
                    {matches.map((match) => {
                        const isTeam1 = match.team1_id === team?.id;
                        const opponentName = isTeam1 ? match.team2_name : match.team1_name;
                        const myTotal = isTeam1 ? match.team1_total : match.team2_total;
                        const theirTotal = isTeam1 ? match.team2_total : match.team1_total;
                        const won = match.winner_id === team?.id;
                        const lost = match.completed && match.winner_id !== team?.id;
                        const matchSubs = submissions.filter(s => s.match_id === match.id);

                        // Get opponent submissions for this match
                        const opponentSubs = (appData?.submissions || []).filter(
                            s => s.match_id === match.id && s.team_id !== team?.id
                        );

                        return (
                            <div key={match.id} className={`card round-result-card ${match.completed ? (won ? 'won' : 'lost') : ''}`}>
                                <div className="round-result-header">
                                    <span className="round-number">R{match.round_number} M{match.match_index + 1}</span>
                                    <span className="round-category">vs {opponentName || 'BYE'}</span>
                                    {won && <span className="badge badge-green">WON</span>}
                                    {lost && <span className="badge badge-red">LOST</span>}
                                    {!match.completed && <span className="badge badge-cyan">IN PROGRESS</span>}
                                </div>
                                <div className="round-result-body">
                                    {[1, 2, 3].map((sr) => {
                                        const sub = matchSubs.find(s => s.sub_round === sr);
                                        const oppSub = opponentSubs.find(s => s.sub_round === sr);
                                        if (!sub && !oppSub) return null;
                                        
                                        return (
                                            <div key={sr} style={{ padding: '0.75rem 0', borderBottom: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                    <span style={{ fontSize: '0.85rem', color: 'var(--accent-purple)', fontWeight: 800 }}>SR{sr}: {SUB_ROUND_CATEGORIES[sr]}</span>
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                                                        <span style={{ color: sub?.score != null ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                                                            {sub?.score != null ? sub.score : '·'}
                                                        </span>
                                                        <span style={{ margin: '0 0.5rem', color: 'var(--text-muted)' }}>-</span>
                                                        <span style={{ color: oppSub?.score != null ? 'var(--accent-red)' : 'var(--text-muted)' }}>
                                                            {oppSub?.score != null ? oppSub.score : '·'}
                                                        </span>
                                                    </span>
                                                </div>
                                                
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontStyle: 'italic', wordBreak: 'break-word', lineHeight: 1.4 }}>
                                                    📝 {sub?.prompt || oppSub?.prompt || 'No prompt recorded.'}
                                                </div>
                                                
                                                {(sub?.reasoning || oppSub?.reasoning) && (
                                                    <div style={{ fontSize: '0.8rem', color: 'var(--accent-cyan)', padding: '0.5rem', background: 'rgba(0, 255, 255, 0.05)', borderRadius: '4px', borderLeft: '2px solid var(--accent-cyan)', lineHeight: 1.4 }}>
                                                        ⚖️ {sub?.reasoning || oppSub?.reasoning}
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '0.5rem', fontWeight: 800 }}>
                                        <span style={{ fontSize: '0.8rem' }}>Total</span>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem' }}>
                                            <span style={{ color: 'var(--accent-green)' }}>{myTotal}</span>
                                            {' - '}
                                            <span style={{ color: 'var(--accent-red)' }}>{theirTotal}</span>
                                        </span>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                    {matches.length === 0 && (
                        <p style={{ color: 'var(--text-muted)', gridColumn: '1 / -1' }}>No matches yet. Bracket not generated.</p>
                    )}
                </div>
            </div>
        </div>
    );
}
