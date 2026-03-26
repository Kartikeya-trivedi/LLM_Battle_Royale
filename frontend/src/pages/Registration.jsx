import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import './Registration.css';

export default function Registration() {
    const { subscribe } = useWebSocket();
    const navigate = useNavigate();
    const [teamName, setTeamName] = useState('');
    const [password, setPassword] = useState('');
    const [members, setMembers] = useState([{ name: '', roll: '' }]);
    const [endpointUrl, setEndpointUrl] = useState('');
    const [teams, setTeams] = useState([]);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [testLoading, setTestLoading] = useState(false);

    const fetchTeams = async () => {
        try {
            const res = await fetch('/api/teams');
            const data = await res.json();
            setTeams(data);
        } catch (e) {
            console.error(e);
        }
    };

    useEffect(() => {
        fetchTeams();
        const unsub = subscribe('team_registered', () => fetchTeams());
        return unsub;
    }, [subscribe]);

    const addMember = () => {
        if (members.length < 4) setMembers([...members, { name: '', roll: '' }]);
    };

    const removeMember = (i) => {
        if (members.length > 1) setMembers(members.filter((_, idx) => idx !== i));
    };

    const updateMember = (i, field, val) => {
        const updated = [...members];
        updated[i] = { ...updated[i], [field]: val };
        setMembers(updated);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const filteredMembers = members.filter((m) => m.name.trim() && m.roll.trim());
        if (!teamName.trim() || filteredMembers.length === 0) {
            setError('Team name and at least one member (with name and roll number) are required');
            setLoading(false);
            return;
        }
        // Validate roll numbers are alphanumeric
        const invalidRoll = filteredMembers.find((m) => !/^[a-zA-Z0-9]+$/.test(m.roll.trim()));
        if (invalidRoll) {
            setError('Roll numbers must be alphanumeric (letters and numbers only)');
            setLoading(false);
            return;
        }
        if (!password.trim() || password.length < 4) {
            setError('Password is required and must be at least 4 characters long');
            setLoading(false);
            return;
        }
        if (!endpointUrl.trim()) {
            setError('LLM endpoint URL is required');
            setLoading(false);
            return;
        }
        if (endpointUrl.trim() !== 'DUMMY' && !endpointUrl.trim().endsWith('.modal.run')) {
            setError('LLM Endpoint URL must end with .modal.run');
            setLoading(false);
            return;
        }

        try {
            const res = await fetch('/api/teams', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: teamName.trim(),
                    password: password.trim(),
                    members: filteredMembers,
                    endpoint_url: endpointUrl.trim(),
                }),
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Registration failed');
            }

            const team = await res.json();
            // Persist login in localStorage so it survives page refresh/tab switch
            localStorage.setItem('team', JSON.stringify(team));
            // Automatically log them in and navigate to the Team Status page
            navigate('/submit', { state: { team } });

        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="page-container registration-page">
            <h1 className="page-title">Team Registration</h1>
            <p className="page-subtitle">Register your team and LLM endpoint for the Battle Royale</p>

            <div className="card reg-form animate-in">
                <form onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label>Team Name</label>
                        <input
                            className="input"
                            type="text"
                            placeholder="Enter team name"
                            value={teamName}
                            onChange={(e) => setTeamName(e.target.value)}
                            required
                        />
                    </div>

                    <div className="form-group">
                        <label>Password</label>
                        <input
                            className="input"
                            type="password"
                            placeholder="Enter password (min 4 characters)"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            minLength={4}
                            required
                        />
                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                            This password will be used to log into your team account during the tournament
                        </p>
                    </div>

                        <div className="form-group">
                            <label>LLM Endpoint URL</label>
                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                <input
                                    className="input"
                                    type="url"
                                    placeholder="https://your-llm-endpoint.com/generate"
                                    value={endpointUrl}
                                    onChange={(e) => { setEndpointUrl(e.target.value); setTestResult(null); }}
                                    required
                                    style={{ fontFamily: 'var(--font-mono)', fontSize: '0.9rem', flex: 1 }}
                                />
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => {
                                        setEndpointUrl('DUMMY');
                                        setTestResult(null);
                                    }}
                                    style={{ whiteSpace: 'nowrap' }}
                                    title="Use dummy endpoint for testing without a real LLM"
                                >
                                    🤖 Use Dummy
                                </button>
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    disabled={testLoading || !endpointUrl.trim()}
                                    onClick={async () => {
                                        setTestLoading(true);
                                        setTestResult(null);
                                        try {
                                            const res = await fetch('/api/teams/test-endpoint', {
                                                method: 'POST',
                                                headers: { 'Content-Type': 'application/json' },
                                                body: JSON.stringify({ url: endpointUrl.trim() }),
                                            });
                                            setTestResult(await res.json());
                                        } catch (e) {
                                            setTestResult({ success: false, error: e.message });
                                        } finally {
                                            setTestLoading(false);
                                        }
                                    }}
                                    style={{ whiteSpace: 'nowrap' }}
                                >
                                    {testLoading ? '⏳ ' : '🧪 Test'}
                                </button>
                            </div>
                            {testResult && (
                                <div style={{
                                    marginTop: '0.5rem',
                                    padding: '0.6rem 0.8rem',
                                    borderRadius: '6px',
                                    fontSize: '0.85rem',
                                    fontFamily: 'var(--font-mono)',
                                    background: testResult.success ? 'rgba(0,255,136,0.1)' : 'rgba(255,68,68,0.1)',
                                    border: `1px solid ${testResult.success ? 'var(--accent-green)' : 'var(--accent-red)'}`,
                                    color: testResult.success ? 'var(--accent-green)' : 'var(--accent-red)',
                                }}>
                                    {testResult.success
                                        ? `✅ Responding! Got: "${(testResult.response || '').slice(0, 100)}" in ${testResult.latency_ms}ms`
                                        : `❌ Failed: ${testResult.error}`
                                    }
                                </div>
                            )}
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                                Your deployed LLM endpoint. Must accept POST with {`{"prompt": "..."}`} and return {`{"response": "..."}`}
                            </p>
                        </div>

                        <div className="form-group">
                            <label>Members (1-4)</label>
                            <div className="members-list">
                                {members.map((member, i) => (
                                    <div className="member-row" key={i} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                                        <span className="member-number">{i + 1}.</span>
                                        <input
                                            className="input"
                                            type="text"
                                            placeholder={`Name`}
                                            value={member.name}
                                            onChange={(e) => updateMember(i, 'name', e.target.value)}
                                            required
                                            style={{ flex: 2 }}
                                        />
                                        <input
                                            className="input"
                                            type="text"
                                            placeholder={`Roll Number`}
                                            value={member.roll}
                                            onChange={(e) => updateMember(i, 'roll', e.target.value)}
                                            pattern="[a-zA-Z0-9]+"
                                            title="Roll number must be alphanumeric"
                                            required
                                            style={{ flex: 1 }}
                                        />
                                        {members.length > 1 && (
                                            <button type="button" className="btn btn-secondary btn-sm" onClick={() => removeMember(i)}>✕</button>
                                        )}
                                    </div>
                                ))}
                            </div>
                            {members.length < 4 && (
                                <button type="button" className="btn btn-secondary btn-sm btn-add-member" onClick={addMember}>
                                    + Add Member
                                </button>
                            )}
                        </div>

                        {error && <p style={{ color: 'var(--accent-red)', marginBottom: '1rem', fontSize: '0.9rem' }}>{error}</p>}

                        <button className="btn btn-primary" type="submit" disabled={loading}>
                            {loading ? 'Registering...' : 'Register Team'}
                        </button>
                    </form>
                </div>

            <div style={{ marginTop: '3rem' }}>
                <h2 className="section-title">
                    Registered Teams <span className="team-count-badge">({teams.length}/64)</span>
                </h2>
                <div className="teams-grid">
                    {teams.map((teamData) => (
                        <div className="card team-mini-card" key={teamData.id}>
                            <h4>{teamData.name}</h4>
                            <div className="members">
                                {teamData.members.map((m, i) => (
                                    <span key={i}>{m.name} ({m.roll}){i < teamData.members.length - 1 ? ', ' : ''}</span>
                                ))}
                            </div>
                            <div style={{ marginTop: '0.4rem', fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {teamData.endpoint_url}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
