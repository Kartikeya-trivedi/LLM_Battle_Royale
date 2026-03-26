import { useState, useEffect, useCallback } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useWebSocket } from '../contexts/WebSocketContext';
import './Navbar.css';

export default function Navbar() {
    const { isConnected } = useWebSocket();
    const location = useLocation();

    const checkRegistered = useCallback(() => {
        const stored = localStorage.getItem('team');
        return !!stored;
    }, []);

    const [isRegistered, setIsRegistered] = useState(checkRegistered);

    // Re-check on every route change (covers post-logout navigation)
    useEffect(() => {
        setIsRegistered(checkRegistered());
    }, [location, checkRegistered]);

    // Listen for cross-tab storage events
    useEffect(() => {
        const handler = () => setIsRegistered(checkRegistered());
        window.addEventListener('storage', handler);
        return () => window.removeEventListener('storage', handler);
    }, [checkRegistered]);

    return (
        <nav className="navbar">
            <NavLink to="/" className="navbar-brand">
                <span className="navbar-logo">inferenceX</span>
                <span className="navbar-tag">Battle Royale</span>
            </NavLink>

            <div className="navbar-links">
                <NavLink to="/" className={({ isActive }) => `navbar-link ${isActive ? 'active' : ''}`} end>
                    Live
                </NavLink>
                {!isRegistered && (
                    <NavLink to="/register" className={({ isActive }) => `navbar-link ${isActive ? 'active' : ''}`}>
                        Register
                    </NavLink>
                )}
                <NavLink to="/submit" className={({ isActive }) => `navbar-link ${isActive ? 'active' : ''}`}>
                    Team Status
                </NavLink>
                <div className={`ws-indicator ${isConnected ? 'connected' : 'disconnected'}`}
                    title={isConnected ? 'Connected' : 'Reconnecting...'} />
            </div>
        </nav>
    );
}
