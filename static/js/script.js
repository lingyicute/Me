(() => {
    'use strict';

    const root = document.documentElement;
    const afterLoad = callback => {
        const schedule = () => {
            if ('requestIdleCallback' in window) requestIdleCallback(callback, { timeout: 2000 });
            else setTimeout(callback, 150);
        };
        if (document.readyState === 'complete') schedule();
        else window.addEventListener('load', schedule, { once: true });
    };

    // Sample the original SVG's linear keyframes without hundreds of CSS animations.
    function sample(frames, percent) {
        let lo = 0;
        let hi = frames.length - 1;
        while (lo + 1 < hi) {
            const mid = (lo + hi) >> 1;
            if (frames[mid][0] <= percent) lo = mid;
            else hi = mid;
        }
        const a = frames[lo];
        const b = frames[hi];
        const mix = Math.max(0, Math.min(1, (percent - a[0]) / (b[0] - a[0] || 1)));
        return a.slice(1).map((value, i) => value + (b[i + 1] - value) * mix);
    }

    function roundedRect(context, x, y, width, height, radius) {
        context.beginPath();
        if (context.roundRect) context.roundRect(x, y, width, height, radius);
        else context.rect(x, y, width, height);
        context.fill();
    }

    function createRenderer(canvas, data) {
        const context = canvas.getContext('2d');
        const grid = document.createElement('canvas');
        const gridContext = grid.getContext('2d');
        if (!context || !gridContext) return null;
        const food = data.cells.map((cell, index) => [cell[1], index])
            .filter(([time]) => time <= 100).sort((a, b) => a[0] - b[0]);
        let scale = 1;
        let previous = -1;
        let nextFood = 0;

        function drawCell(index, eaten) {
            const x = Math.floor(index / 7) * 16 + 2;
            const y = (index % 7) * 16 + 2;
            gridContext.clearRect(x - 1, y - 1, 14, 14);
            gridContext.fillStyle = data.colors[eaten ? 0 : data.cells[index][0]];
            roundedRect(gridContext, x, y, 12, 12, 2);
            gridContext.strokeStyle = data.border;
            gridContext.lineWidth = 1;
            gridContext.stroke();
        }

        function resetGrid(percent) {
            gridContext.setTransform(1, 0, 0, 1, 0, 0);
            gridContext.clearRect(0, 0, grid.width, grid.height);
            gridContext.setTransform(scale, 0, 0, scale, 16 * scale, 32 * scale);
            data.cells.forEach((cell, index) => drawCell(index, cell[1] <= percent));
            nextFood = food.findIndex(([time]) => time > percent);
            if (nextFood < 0) nextFood = food.length;
        }

        function draw(percent) {
            if (percent < previous) resetGrid(percent);
            while (nextFood < food.length && food[nextFood][0] <= percent) {
                drawCell(food[nextFood][1], true);
                nextFood++;
            }
            previous = percent;
            // The 367/371-cell grid is rasterized once, then only eaten cells change.
            context.setTransform(1, 0, 0, 1, 0, 0);
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.drawImage(grid, 0, 0);
            context.setTransform(scale, 0, 0, scale, 16 * scale, 32 * scale);
            for (const bar of data.bars) {
                const [x, y, width, height] = bar.rect;
                context.fillStyle = data.colors[bar.color];
                context.fillRect(x, y, width * sample(bar.frames, percent)[0], height);
            }
            context.fillStyle = data.snakeColor;
            for (const segment of data.segments) {
                const [dx, dy] = sample(segment.frames, percent);
                const [x, y, width, height, radius] = segment.rect;
                roundedRect(context, x + dx, y + dy, width, height, radius);
            }
        }

        return {
            draw,
            resize(width, percent) {
                // Cap backing-store density; this is a small decorative animation.
                const density = Math.min(window.devicePixelRatio || 1, 2);
                const pixels = Math.max(1, Math.round(width * density));
                if (canvas.width === pixels && previous >= 0) return;
                canvas.width = grid.width = pixels;
                canvas.height = grid.height = Math.max(1, Math.round(pixels * 192 / 880));
                scale = pixels / 880;
                resetGrid(percent);
                draw(percent);
            }
        };
    }

    function createSnakePlayer() {
        const stage = document.querySelector('.snake-stage');
        const fallback = document.getElementById('tanChiShe');
        const canvas = document.getElementById('snake-canvas');
        const button = document.getElementById('snake-toggle');
        const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
        const connection = navigator.connection;
        const capable = 'IntersectionObserver' in window && !!canvas.getContext('2d');
        const cache = new Map();
        let theme = 'Light';
        let version = 0;
        let pending = false;
        let ready = false;
        let visible = false;
        let enabled = capable && !reducedMotion.matches && !connection?.saveData;
        let renderer = null;
        let duration = 1;
        let elapsed = 0;
        let startedAt = 0;
        let lastDraw = -Infinity;
        let playing = false;
        let frameId = 0;
        let modalOpen = false;
        let stageWidth = stage.getBoundingClientRect().width;
        button.hidden = !capable;

        const percentAt = now => ((elapsed + (playing ? now - startedAt : 0)) % duration) / duration * 100;
        function updateButton() {
            button.setAttribute('aria-pressed', String(enabled));
        }
        function stop() {
            if (playing) elapsed += performance.now() - startedAt;
            playing = false;
            cancelAnimationFrame(frameId);
            frameId = 0;
            stage.dataset.playerState = renderer ? 'paused' : 'static';
        }
        function frame(now) {
            if (!playing) return;
            // At most 30 draws/second, regardless of a 60/120/144 Hz display.
            if (now - lastDraw >= 1000 / 30) {
                renderer.draw(percentAt(now));
                lastDraw = now;
            }
            frameId = requestAnimationFrame(frame);
        }
        function start() {
            if (playing || !renderer) return;
            startedAt = performance.now();
            lastDraw = -Infinity;
            playing = true;
            stage.dataset.playerState = 'playing';
            frameId = requestAnimationFrame(frame);
        }
        const shouldPlay = () => enabled && visible && !document.hidden && !modalOpen;

        async function reconcile() {
            updateButton();
            if (!ready || !shouldPlay()) { stop(); return; }
            if (renderer) { start(); return; }
            if (pending) return;
            pending = true;
            const currentVersion = version;
            const key = theme;
            try {
                if (!cache.has(key)) {
                    const request = fetch(`./static/data/snake-${key}.json`)
                        .then(response => {
                            if (!response.ok) throw new Error('Snake data unavailable');
                            return response.json();
                        }).catch(error => { cache.delete(key); throw error; });
                    cache.set(key, request);
                }
                const data = await cache.get(key);
                // A slow Light response must never overwrite a newer Dark selection.
                if (currentVersion !== version) return;
                renderer = createRenderer(canvas, data);
                if (!renderer) { button.hidden = true; return; }
                duration = data.duration;
                renderer.resize(stageWidth, 0);
                canvas.hidden = false;
                fallback.style.visibility = 'hidden';
                stage.dataset.playerState = 'paused';
                if (shouldPlay()) start();
            } catch {
                // The static image still works if fetch/Canvas is blocked (e.g. file://).
                if (currentVersion === version) stage.dataset.playerState = 'static';
            } finally {
                if (currentVersion === version) pending = false;
            }
        }

        if (capable) {
            const observer = new IntersectionObserver(([entry]) => {
                visible = entry.isIntersecting && entry.intersectionRatio > 0;
                reconcile();
            });
            observer.observe(stage);
            if ('ResizeObserver' in window) {
                new ResizeObserver(([entry]) => {
                    stageWidth = entry.contentRect.width;
                    if (renderer) renderer.resize(stageWidth, percentAt(performance.now()));
                }).observe(stage);
            } else {
                window.addEventListener('resize', () => {
                    stageWidth = stage.getBoundingClientRect().width;
                    if (renderer) renderer.resize(stageWidth, percentAt(performance.now()));
                }, { passive: true });
            }
        }
        document.addEventListener('visibilitychange', reconcile);
        // pagehide/pageshow also cover back-forward cache restores.
        window.addEventListener('pagehide', stop);
        window.addEventListener('pageshow', reconcile);
        reducedMotion.addEventListener('change', () => {
            enabled = capable && !reducedMotion.matches && !connection?.saveData;
            reconcile();
        });
        button.addEventListener('click', () => {
            enabled = !enabled;
            ready = true; // Explicit intent need not wait for the idle enhancement.
            reconcile();
        });
        afterLoad(() => { ready = true; reconcile(); });

        return {
            setTheme(nextTheme) {
                stop();
                version++;
                pending = false;
                theme = nextTheme;
                renderer = null;
                elapsed = 0;
                canvas.hidden = true;
                fallback.style.visibility = '';
                fallback.src = `./static/svg/snake-${theme}-static.svg`;
                stage.dataset.playerState = 'static';
                reconcile();
            },
            setModalOpen(open) { modalOpen = open; reconcile(); }
        };
    }

    const snake = createSnakePlayer();
    const themeButton = document.getElementById('theme-toggle');
    const currentTheme = () => root.dataset.theme === 'Dark' ? 'Dark' : 'Light';
    function syncTheme() {
        const theme = currentTheme();
        themeButton.setAttribute('aria-checked', String(theme === 'Dark'));
        snake.setTheme(theme);
    }
    themeButton.addEventListener('click', () => {
        const theme = currentTheme() === 'Dark' ? 'Light' : 'Dark';
        root.dataset.theme = theme;
        try {
            document.cookie = `themeState=${theme}; Max-Age=31536000; Path=/; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
        } catch { /* The theme still works when storage is unavailable. */ }
        syncTheme();
    });
    syncTheme();

    const dialog = document.getElementById('avatar-dialog');
    const avatarButton = document.getElementById('avatar-button');
    const avatar = document.getElementById('avatar-preview');
    function closeDialog() {
        if (typeof dialog.close === 'function') dialog.close();
        else { dialog.removeAttribute('open'); snake.setModalOpen(false); avatarButton.focus(); }
    }
    avatarButton.addEventListener('click', () => {
        if (!avatar.getAttribute('src')) avatar.src = './static/img/logo.webp';
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        snake.setModalOpen(true);
        document.getElementById('dialog-close').focus();
    });
    document.getElementById('dialog-close').addEventListener('click', closeDialog);
    dialog.addEventListener('click', event => {
        if (event.target === dialog) closeDialog();
    });
    dialog.addEventListener('close', () => { snake.setModalOpen(false); avatarButton.focus(); });

    // Analytics is deliberately outside the critical rendering/load path.
    // A blocked provider leaves the '-' placeholder and cannot hide the page.
    afterLoad(() => {
        if (!/^https?:$/.test(location.protocol)) return;
        const counter = document.createElement('script');
        counter.src = 'https://events.vercount.one/js';
        counter.async = true;
        counter.dataset.cfasync = 'false';
        document.head.append(counter);
    });
})();
