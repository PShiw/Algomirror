// Theme management for AlgoMirror
(function() {
    'use strict';

    const THEME_KEY = 'theme';  // Must match base.html
    const DEFAULT_THEME = 'dark';
    
    // Available themes
    const themes = {
        light: 'light',
        dark: 'dark',
        auto: 'auto'
    };
    
    // Get system theme preference
    function getSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }
    
    // Apply theme to document
    function applyTheme(theme) {
        if (theme === 'auto') {
            theme = getSystemTheme();
        }
        
        document.documentElement.setAttribute('data-theme', theme);
        
        // Update theme color meta tag
        const themeColorMeta = document.querySelector('meta[name="theme-color"]');
        if (themeColorMeta) {
            themeColorMeta.content = theme === 'dark' ? '#1f2937' : '#ffffff';
        }
        
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('themechange', { 
            detail: { theme: theme } 
        }));
    }
    
    // Get saved theme or default
    function getSavedTheme() {
        try {
            return localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
        } catch (e) {
            console.warn('Unable to access localStorage for theme:', e);
            return DEFAULT_THEME;
        }
    }
    
    // Save theme to localStorage
    function saveTheme(theme) {
        try {
            if (theme === 'auto') {
                localStorage.removeItem(THEME_KEY);
            } else {
                localStorage.setItem(THEME_KEY, theme);
            }
        } catch (e) {
            console.warn('Unable to save theme to localStorage:', e);
        }
    }
    
    // Set theme and save preference
    function setTheme(theme) {
        if (!themes[theme]) {
            console.warn('Invalid theme:', theme);
            return;
        }
        
        applyTheme(theme);
        saveTheme(theme);
    }
    
    // Initialize theme on page load
    function initTheme() {
        const savedTheme = getSavedTheme();
        applyTheme(savedTheme);
        
        // Listen for system theme changes
        if (window.matchMedia) {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            mediaQuery.addListener(function(e) {
                if (getSavedTheme() === 'auto') {
                    applyTheme('auto');
                }
            });
        }
    }
    
    // Toggle between light and dark (skip auto)
    function toggleTheme() {
        const currentTheme = getSavedTheme();
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
    }
    
    // Get current effective theme (resolves 'auto')
    function getCurrentTheme() {
        const savedTheme = getSavedTheme();
        return savedTheme === 'auto' ? getSystemTheme() : savedTheme;
    }
    
    // Export functions to global scope
    window.AlgoMirrorTheme = {
        setTheme: setTheme,
        toggleTheme: toggleTheme,
        getCurrentTheme: getCurrentTheme,
        getSavedTheme: getSavedTheme,
        themes: themes
    };
    
    // For backward compatibility
    window.setTheme = setTheme;
    
    // Initialize theme immediately
    initTheme();
    
    // Re-initialize on DOM content loaded (in case script loads before DOM)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTheme);
    }
})();