// Readability: Frontend module: keep browser state, API calls, and UI updates easy to follow.
﻿// CASM v20 — Micro-animations & UI enhancements
(function() {
    'use strict';

    // Animate counting numbers
    // Section: handle the animate counter workflow.
    function animateCounter(el, target, duration) {
        if (!el) return;
        const start = 0;
        const startTime = performance.now();
        target = parseInt(target, 10);
        // Choose the correct browser state branch before continuing.
        if (isNaN(target)) return;

        // Section: handle the tick workflow.
        function tick(now) {
            const elapsed = now - startTime;
            const progress = Math.min(elapsed / duration, 1);
            // Ease out cubic
            const eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.round(start + eased * (target - start));
            if (progress < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    // Observe summary values and animate on first appearance
    // Section: handle the setup counter animations workflow.
    function setupCounterAnimations() {
        const observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                // Choose the correct browser state branch before continuing.
                if (entry.isIntersecting) {
                    const el = entry.target;
                    const raw = el.dataset.target || el.textContent.trim();
                    const num = parseInt(raw, 10);
                    // Choose the correct browser state branch before continuing.
                    if (!isNaN(num) && num > 0) {
                        el.dataset.target = raw;
                        animateCounter(el, num, 900);
                    }
                    observer.unobserve(el);
                }
            });
        }, { threshold: 0.4 });

        document.querySelectorAll('.summary-block .value').forEach(function(el) {
            observer.observe(el);
        });
    }

    // Card entrance animations
    // Section: handle the setup card animations workflow.
    function setupCardAnimations() {
        const style = document.createElement('style');
        style.textContent = `
            @keyframes cardFadeIn {
                from { opacity: 0; transform: translateY(16px); }
                to   { opacity: 1; transform: translateY(0); }
            }
            .card {
                animation: cardFadeIn 0.4s ease both;
            }
            .card:nth-child(1) { animation-delay: 0.05s; }
            .card:nth-child(2) { animation-delay: 0.10s; }
            .card:nth-child(3) { animation-delay: 0.15s; }
            .card:nth-child(4) { animation-delay: 0.20s; }
            .card:nth-child(5) { animation-delay: 0.25s; }
            .card:nth-child(6) { animation-delay: 0.30s; }
            .ops-hero {
                animation: cardFadeIn 0.45s ease both;
            }
        `;
        document.head.appendChild(style);
    }

    // Re-run counter animation on data refresh
    // Section: handle the observe value changes workflow.
    function observeValueChanges() {
        const mo = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                // Choose the correct browser state branch before continuing.
                if (m.type === 'childList' || m.type === 'characterData') {
                    const target = m.target.nodeType === 3 ? m.target.parentElement : m.target;
                    // Choose the correct browser state branch before continuing.
                    if (target && target.classList && target.classList.contains('value')) {
                        const num = parseInt(target.textContent, 10);
                        // Choose the correct browser state branch before continuing.
                        if (!isNaN(num) && num > 0) {
                            animateCounter(target, num, 700);
                        }
                    }
                }
            });
        });
        document.querySelectorAll('.summary-block .value, #safety-score').forEach(function(el) {
            mo.observe(el, { childList: true, characterData: true, subtree: true });
        });
    }

    // Init on DOM ready
    // Section: handle the init workflow.
    function init() {
        setupCardAnimations();
        setupCounterAnimations();
        observeValueChanges();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-run after each SPA navigation
    window.addEventListener('ppe-page:changed', function() {
        setTimeout(function() {
            setupCounterAnimations();
            observeValueChanges();
        }, 150);
    });
})();
