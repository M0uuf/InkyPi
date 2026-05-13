(function () {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    if (!csrfToken || !window.fetch) {
        return;
    }

    const protectedMethods = new Set(['POST', 'PUT', 'DELETE', 'PATCH']);
    const originalFetch = window.fetch.bind(window);

    window.fetch = function (resource, options) {
        const requestOptions = options || {};
        const method = (requestOptions.method || 'GET').toUpperCase();
        if (!protectedMethods.has(method)) {
            return originalFetch(resource, requestOptions);
        }

        const requestUrl = typeof resource === 'string' ? resource : resource.url;
        const target = new URL(requestUrl, window.location.href);
        if (target.origin !== window.location.origin) {
            return originalFetch(resource, requestOptions);
        }

        const headers = new Headers(requestOptions.headers || {});
        if (!headers.has('X-CSRF-Token')) {
            headers.set('X-CSRF-Token', csrfToken);
        }

        return originalFetch(resource, {
            ...requestOptions,
            headers
        });
    };
})();
