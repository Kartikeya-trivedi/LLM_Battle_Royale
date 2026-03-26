import { useState, useEffect } from 'react';
import { useWebSocket } from '../contexts/WebSocketContext';
import './Timer.css';

const LABEL_MAP = {
    sub_round_break: 'Sub-Round Break',
    round_break: 'Round Break',
};

export default function Timer({ compact = false }) {
    const { subscribe } = useWebSocket();
    const [remaining, setRemaining] = useState(null);
    const [total, setTotal] = useState(300);
    const [active, setActive] = useState(false);
    const [label, setLabel] = useState('');

    useEffect(() => {
        const unsub1 = subscribe('timer_start', (data) => {
            setTotal(data.timer_seconds);
            setRemaining(data.timer_seconds);
            setActive(true);
            setLabel(data.label || '');
        });
        const unsub2 = subscribe('timer_tick', (data) => {
            setRemaining(data.remaining);
        });
        const unsub3 = subscribe('timer_end', () => {
            setActive(false);
            setLabel('');
        });
        return () => { unsub1(); unsub2(); unsub3(); };
    }, [subscribe]);

    const minutes = Math.floor((remaining ?? 0) / 60);
    const seconds = (remaining ?? 0) % 60;
    const pct = total > 0 ? ((remaining ?? 0) / total) * 100 : 0;

    let timerClass = '';
    if (remaining === null || !active) timerClass = 'ended';
    else if (remaining <= 30) timerClass = 'critical';
    else if (remaining <= 60) timerClass = 'warning';

    const displayLabel = active
        ? (LABEL_MAP[label] || 'Round Timer')
        : remaining === null
            ? 'Waiting...'
            : "Time's up!";

    // Compact mode: hide when not active and remaining is null
    if (compact && remaining === null && !active) {
        return (
            <div className="timer-container timer-compact timer-inactive">
                <div className="timer-label">Timer</div>
                <div className="timer-display ended">--:--</div>
            </div>
        );
    }

    return (
        <div className={`timer-container ${compact ? 'timer-compact' : ''}`}>
            <div className="timer-label">{displayLabel}</div>
            <div className={`timer-display ${timerClass}`}>
                {String(minutes).padStart(2, '0')}:{String(seconds).padStart(2, '0')}
            </div>
            <div className="timer-bar-wrapper">
                <div className={`timer-bar ${timerClass}`} style={{ width: `${pct}%` }} />
            </div>
        </div>
    );
}
