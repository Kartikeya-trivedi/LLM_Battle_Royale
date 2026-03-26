import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';

const WebSocketContext = createContext(null);

function getWebSocketUrl() {
    const configuredUrl = import.meta.env.VITE_WS_URL;
    if (configuredUrl) {
        if (configuredUrl.startsWith('http://')) return configuredUrl.replace('http://', 'ws://');
        if (configuredUrl.startsWith('https://')) return configuredUrl.replace('https://', 'wss://');
        return configuredUrl;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws`;
}

export function WebSocketProvider({ children }) {
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef(null);
    const listenersRef = useRef({});
    const reconnectTimeoutRef = useRef(null);
    const reconnectDelayRef = useRef(2000);  // Start at 2s, exponential backoff

    const connect = useCallback(() => {
        const wsUrl = getWebSocketUrl();

        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('[WS] Connected');
            setIsConnected(true);
            reconnectDelayRef.current = 2000;  // Reset backoff on success
        };

        ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                const { type, data } = message;

                // Notify all listeners for this event type
                const callbacks = listenersRef.current[type] || [];
                callbacks.forEach((cb) => cb(data));

                // Also notify wildcard listeners
                const wildcardCallbacks = listenersRef.current['*'] || [];
                wildcardCallbacks.forEach((cb) => cb(type, data));
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };

        ws.onclose = () => {
            const delay = reconnectDelayRef.current;
            console.log(`[WS] Disconnected, reconnecting in ${delay / 1000}s...`);
            setIsConnected(false);
            reconnectTimeoutRef.current = setTimeout(connect, delay);
            // Exponential backoff: 2s -> 4s -> 8s -> 16s -> max 30s
            reconnectDelayRef.current = Math.min(delay * 2, 30000);
        };

        ws.onerror = (err) => {
            console.error('[WS] Error:', err);
            ws.close();
        };

        wsRef.current = ws;
    }, []);

    useEffect(() => {
        connect();
        return () => {
            if (wsRef.current) wsRef.current.close();
            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        };
    }, [connect]);

    const subscribe = useCallback((eventType, callback) => {
        if (!listenersRef.current[eventType]) {
            listenersRef.current[eventType] = [];
        }
        listenersRef.current[eventType].push(callback);

        // Return unsubscribe function
        return () => {
            listenersRef.current[eventType] = listenersRef.current[eventType].filter(
                (cb) => cb !== callback
            );
        };
    }, []);

    return (
        <WebSocketContext.Provider value={{ isConnected, subscribe }}>
            {/* Reconnection banner */}
            {!isConnected && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    zIndex: 9999,
                    background: 'linear-gradient(90deg, #ff4444, #ff6b35)',
                    color: '#fff',
                    textAlign: 'center',
                    padding: '0.4rem 1rem',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    letterSpacing: '0.5px',
                }}>
                    ⚡ Connection lost — reconnecting...
                </div>
            )}
            {children}
        </WebSocketContext.Provider>
    );
}

export function useWebSocket() {
    return useContext(WebSocketContext);
}
