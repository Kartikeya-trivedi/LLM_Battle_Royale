function normalizeBaseUrl(rawUrl) {
    if (!rawUrl) return '';
    return rawUrl.trim().replace(/\/$/, '');
}

function resolveApiBaseUrl() {
    return normalizeBaseUrl(import.meta.env.VITE_BACKEND_URL);
}

function mapApiUrl(input, apiBaseUrl) {
    if (!apiBaseUrl) return input;

    if (typeof input === 'string') {
        if (input.startsWith('/api/')) return `${apiBaseUrl}${input}`;
        return input;
    }

    if (input instanceof URL) {
        if (input.pathname.startsWith('/api/') && input.origin === window.location.origin) {
            return `${apiBaseUrl}${input.pathname}${input.search}${input.hash}`;
        }
        return input;
    }

    if (input instanceof Request) {
        const mapped = mapApiUrl(input.url, apiBaseUrl);
        if (mapped === input.url) return input;
        return new Request(mapped, input);
    }

    return input;
}

export function installApiBaseFetch() {
    const apiBaseUrl = resolveApiBaseUrl();
    if (!apiBaseUrl) return;
    if (window.__apiBaseFetchInstalled) return;

    const originalFetch = window.fetch.bind(window);

    window.fetch = (input, init) => {
        const mappedInput = mapApiUrl(input, apiBaseUrl);
        return originalFetch(mappedInput, init);
    };

    window.__apiBaseFetchInstalled = true;
}
