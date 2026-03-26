import { useState, useEffect } from 'react';
import { useWebSocket } from '../contexts/WebSocketContext';
import Bracket from '../components/Bracket';
import Timer from '../components/Timer';
import Leaderboard from '../components/Leaderboard';
import './ParticipantView.css';

const SUB_ROUND_CATEGORIES = {
    1: 'Complex Puzzle',
    2: 'Math',
    3: 'General Knowledge',
};

export default function ParticipantView() {
    const { subscribe } = useWebSocket();
    const [currentBracketRound, setCurrentBracketRound] = useState(0);
    const [currentSubRound, setCurrentSubRound] = useState(0);
    const [champion, setChampion] = useState(null);
    const [statusMessage, setStatusMessage] = useState('');
    const [battleStatus, setBattleStatus] = useState(null);
    const [currentPrompt, setCurrentPrompt] = useState('');

    useEffect(() => {
        const fetchState = async () => {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                setCurrentBracketRound(data.current_bracket_round || 0);
                setCurrentSubRound(data.current_sub_round || 0);
                setChampion(data.champion || null);
            } catch (e) {
                console.error(e);
            }
        };
        fetchState();

        const unsubs = [
            subscribe('sub_round_start', (data) => {
                setCurrentBracketRound(data.bracket_round);
                setBattleStatus('running');
                setStatusMessage(`⚔️ ${data.category} — ${data.total_matches} matches running...`);
            }),
            subscribe('match_scored', (data) => {
                setStatusMessage(`⚡ ${data.team1_name} (${data.team1_sub_score}) vs ${data.team2_name} (${data.team2_sub_score})`);
            }),
            subscribe('sub_round_complete', (data) => {
                setBattleStatus(null);
                setStatusMessage(`✅ Sub-round ${data.sub_round} complete! (${data.sub_rounds_completed.length}/3)`);
            }),
            subscribe('bracket_round_complete', (data) => {
                setBattleStatus(null);
                setStatusMessage(`🏁 Bracket round ${data.bracket_round} complete!`);
            }),
            subscribe('bracket_update', (data) => {
                setCurrentBracketRound(data.current_bracket_round || 0);
                if (data.auto_advanced) {
                    setStatusMessage(`🚀 Advanced to bracket round ${data.current_bracket_round}`);
                }
            }),
            subscribe('sub_round_prompt_set', (data) => {
                setCurrentSubRound(data.sub_round);
                setCurrentPrompt(data.prompt);
                setStatusMessage(`📝 ${data.category} question posted!`);
            }),
            subscribe('champion', (data) => {
                setChampion(data.team_name);
                setBattleStatus(null);
                setStatusMessage(`🏆 CHAMPION: ${data.team_name}!`);
            }),
        ];
        return () => unsubs.forEach(fn => fn());
    }, [subscribe]);

    return (
        <div className="page-container participant-page">

            {/* ── Header row: title + compact timer ── */}
            <div className="pv-header">
                <div className="pv-title-block">
                    <h1 className="page-title" style={{ marginBottom: 0 }}>
                        LLM Battle Royale
                    </h1>
                    {currentBracketRound > 0 && (
                        <span className="pv-round-badge">
                            Round {currentBracketRound}
                            {currentSubRound > 0 && ` · SR${currentSubRound}: ${SUB_ROUND_CATEGORIES[currentSubRound]}`}
                        </span>
                    )}
                </div>
                <div className="pv-timer-corner">
                    <Timer compact />
                </div>
            </div>

            {/* ── Status banner ── */}
            {statusMessage && (
                <div className={`participant-status ${battleStatus ? 'active' : 'done'}`}>
                    {statusMessage}
                    {battleStatus && <span className="status-dot" />}
                </div>
            )}

            {/* ── Champion splash ── */}
            {champion && (
                <div className="card champion-splash animate-in">
                    <div style={{ fontSize: '4rem' }}>🏆</div>
                    <h2 className="champion-splash-name">
                        {typeof champion === 'string' ? champion : 'Champion Crowned!'}
                    </h2>
                    <p style={{ color: 'var(--text-secondary)' }}>The LLM Battle Royale is over!</p>
                </div>
            )}

            {/* ── Current challenge prompt ── */}
            {currentPrompt && !champion && (
                <div className="card current-challenge animate-in">
                    <h3 className="current-challenge-label">Current Challenge</h3>
                    <div className="current-challenge-text">{currentPrompt}</div>
                </div>
            )}

            {/* ── Leaderboard front and centre ── */}
            <div className="pv-leaderboard-section">
                <div className="card pv-leaderboard-card">
                    <div className="pv-section-header">
                        <span className="pv-section-icon">🏅</span>
                        <h2 className="pv-section-title">Live Standings</h2>
                    </div>
                    <Leaderboard />
                </div>
            </div>

            {/* ── Visual bracket ── */}
            <div className="pv-bracket-section">
                <div className="pv-section-header" style={{ marginBottom: '1.25rem' }}>
                    <span className="pv-section-icon">⚔️</span>
                    <h2 className="pv-section-title">Tournament Bracket</h2>
                </div>
                <Bracket currentBracketRound={currentBracketRound} />
            </div>
        </div>
    );
}
