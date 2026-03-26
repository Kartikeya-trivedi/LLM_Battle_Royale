import { useState, useEffect } from 'react';
import { useWebSocket } from '../contexts/WebSocketContext';
import './Bracket.css';

const ROUND_NAMES = {
    1: 'Round of 64',
    2: 'Round of 32',
    3: 'Sweet 16',
    4: 'Quarter-Finals',
    5: 'Semi-Finals',
    6: 'Final',
};

// Layout constants (must match CSS .bk-match height)
const CARD_H = 60;   // px — match card height
const SLOT_GAP = 20; // px — gap between matches in round 1
const UNIT = CARD_H + SLOT_GAP; // 80px per slot

// Top of match idx in colIdx:
//   slotHeight = 2^colIdx * UNIT
//   top = idx * slotHeight + (slotHeight - CARD_H) / 2
function matchTop(colIdx, idx) {
    const slotH = Math.pow(2, colIdx) * UNIT;
    return idx * slotH + (slotH - CARD_H) / 2;
}

// Total column height for matchCount matches at colIdx
function colHeight(colIdx, matchCount) {
    const slotH = Math.pow(2, colIdx) * UNIT;
    return matchCount * slotH;
}

export default function Bracket({ currentBracketRound }) {
    const { subscribe } = useWebSocket();
    const [matches, setMatches] = useState([]);
    const [champion, setChampion] = useState(null);

    const fetchBracket = async () => {
        try {
            const res = await fetch('/api/bracket');
            const data = await res.json();
            setMatches(data.matches || []);
            setChampion(data.champion || null);
        } catch (e) {
            console.error('Failed to fetch bracket:', e);
        }
    };

    useEffect(() => {
        fetchBracket();
        const unsubs = [
            subscribe('bracket_update', () => fetchBracket()),
            subscribe('match_scored', () => fetchBracket()),
            subscribe('bracket_round_complete', () => fetchBracket()),
            subscribe('champion', (data) => { setChampion(data.team_id); fetchBracket(); }),
        ];
        return () => unsubs.forEach(fn => fn());
    }, [subscribe]);

    const rounds = {};
    matches.forEach((m) => {
        if (!rounds[m.round_number]) rounds[m.round_number] = [];
        rounds[m.round_number].push(m);
    });
    const sortedRoundNums = Object.keys(rounds).map(Number).sort((a, b) => a - b);

    if (sortedRoundNums.length === 0) {
        return (
            <div className="no-bracket-msg">
                <div className="no-bracket-icon">⚔️</div>
                <p>Bracket not generated yet.</p>
                <p className="no-bracket-sub">Waiting for admin to seed teams and generate the bracket.</p>
            </div>
        );
    }

    const championName = champion
        ? matches.find(m => m.winner_id === champion)?.winner_name
          || matches.find(m => m.team1_id === champion)?.team1_name
          || 'Champion'
        : null;

    // Total height is determined by the first (largest) round
    const firstRound = sortedRoundNums[0];
    const firstRoundCount = rounds[firstRound].length;
    const totalH = colHeight(0, firstRoundCount);

    return (
        <div className="bracket-outer">
            <div className="bracket-scroll">
                <div className="bracket-flex" style={{ height: totalH + 48 /* label */ }}>
                    {sortedRoundNums.map((roundNum, colIdx) => {
                        const roundMatches = rounds[roundNum]
                            .slice()
                            .sort((a, b) => a.match_index - b.match_index);
                        const isActive = roundNum === currentBracketRound;
                        const slotH = Math.pow(2, colIdx) * UNIT;
                        const isLast = colIdx === sortedRoundNums.length - 1;

                        return (
                            <div
                                key={roundNum}
                                className={`bracket-col ${isActive ? 'bracket-col-active' : ''}`}
                            >
                                {/* Round label */}
                                <div className={`bracket-round-label ${isActive ? 'active-label' : ''}`}>
                                    {ROUND_NAMES[roundNum] || `Round ${roundNum}`}
                                </div>

                                {/* Match cards + connectors */}
                                <div className="bracket-col-body" style={{ height: totalH }}>
                                    {roundMatches.map((match, idx) => {
                                        const top = matchTop(colIdx, idx);
                                        const midY = top + CARD_H / 2;
                                        // Vertical bar height = distance from this match mid to next match mid
                                        const vbarHeight = slotH;
                                        const isPaired = idx % 2 === 0 && idx + 1 < roundMatches.length;

                                        return (
                                            <div
                                                key={match.id}
                                                className="bk-match-slot"
                                                style={{ top, position: 'absolute', left: 0, right: 0 }}
                                            >
                                                {/* Left connector (from previous column) */}
                                                {colIdx > 0 && (
                                                    <div className="bk-conn-left" />
                                                )}

                                                {/* Match card */}
                                                <MatchCard
                                                    match={match}
                                                    isActive={isActive}
                                                />

                                                {/* Right connector + vertical bar connecting pair */}
                                                {!isLast && (
                                                    <>
                                                        <div className="bk-conn-right" />
                                                        {isPaired && (
                                                            <div
                                                                className="bk-vbar"
                                                                style={{ height: vbarHeight - CARD_H / 2 + CARD_H / 2, top: CARD_H / 2 }}
                                                            />
                                                        )}
                                                        {!isPaired && idx % 2 === 1 && (
                                                            /* bottom of pair: bar going up to join top sibling */
                                                            <div
                                                                className="bk-vbar bk-vbar-up"
                                                                style={{ height: vbarHeight - CARD_H / 2 + CARD_H / 2, bottom: CARD_H / 2, top: 'auto' }}
                                                            />
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        );
                    })}

                    {/* Final champion node */}
                    {championName && (
                        <div className="bracket-champion-col" style={{ height: totalH + 48 }}>
                            <div className="bracket-champion-node">
                                <div className="champion-crown">🏆</div>
                                <div className="champion-col-name">{championName}</div>
                                <div className="champion-col-label">CHAMPION</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function MatchCard({ match, isActive }) {
    const isBye = !(match.team1_id && match.team2_id);
    const hasResult = !!match.winner_id;

    return (
        <div className={`bk-match ${isActive ? 'bk-match-active' : ''} ${hasResult ? 'bk-match-done' : ''} ${isBye ? 'bk-match-bye' : ''}`}>
            <TeamSlot
                name={match.team1_name}
                seed={match.team1_seed}
                score={match.team1_total}
                isWinner={hasResult && match.winner_id === match.team1_id}
                isLoser={hasResult && match.winner_id !== match.team1_id}
                isBye={isBye && !match.team1_id}
            />
            <div className="bk-divider" />
            <TeamSlot
                name={match.team2_name}
                seed={match.team2_seed}
                score={match.team2_total}
                isWinner={hasResult && match.winner_id === match.team2_id}
                isLoser={hasResult && match.winner_id !== match.team2_id}
                isBye={isBye && !match.team2_id}
            />
        </div>
    );
}

function TeamSlot({ name, seed, score, isWinner, isLoser, isBye }) {
    return (
        <div className={`bk-team ${isWinner ? 'bk-winner' : ''} ${isLoser ? 'bk-loser' : ''} ${isBye ? 'bk-bye-slot' : ''}`}>
            {isWinner && <div className="bk-winner-bar" />}
            <span className="bk-seed">{seed ? `#${seed}` : '·'}</span>
            <span className="bk-name">{isBye ? 'BYE' : (name || 'TBD')}</span>
            {score > 0 && (
                <span className={`bk-score ${isWinner ? 'bk-score-win' : 'bk-score-lose'}`}>
                    {Number.isInteger(score) ? score : score.toFixed(1)}
                </span>
            )}
        </div>
    );
}
