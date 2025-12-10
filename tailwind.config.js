/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        'brand': {
          DEFAULT: '#3ECF8E',
          50: '#E6FAF2',
          100: '#CCF5E5',
          200: '#99EBCB',
          300: '#66E0B1',
          400: '#3ECF8E',
          500: '#3ECF8E',
          600: '#32A672',
          700: '#267D56',
          800: '#1A533A',
          900: '#0D2A1D',
        },
        'scale': {
          0: '#18181b',
          50: '#1f1f23',
          100: '#27272a',
          200: '#2e2e33',
          300: '#3a3a3f',
          400: '#52525b',
          500: '#71717a',
          600: '#a1a1aa',
          700: '#d4d4d8',
          800: '#e4e4e7',
          900: '#f4f4f5',
          1000: '#fafafa',
          1100: '#fcfcfc',
          1200: '#ffffff',
        },
        /* Trading Terminal Colors */
        'terminal': {
          'black': '#0a0a0c',
          'darker': '#0d0e12',
          'dark': '#12141a',
          'panel': '#161922',
          'border': '#1e222d',
          'muted': '#363a45',
          'text': '#787b86',
          'light': '#b2b5be',
          'white': '#d1d4dc',
        },
        'profit': {
          DEFAULT: '#26a69a',
          light: '#4db6ac',
          dark: '#00897b',
          glow: 'rgba(38, 166, 154, 0.3)',
        },
        'loss': {
          DEFAULT: '#ef5350',
          light: '#ff7043',
          dark: '#d32f2f',
          glow: 'rgba(239, 83, 80, 0.3)',
        },
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', 'monospace'],
        'terminal': ['JetBrains Mono', 'Consolas', 'Monaco', 'monospace'],
      },
      animation: {
        'slide-in': 'slideIn 0.2s ease-out',
        'fade-in': 'fadeIn 0.15s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'ticker': 'ticker 20s linear infinite',
        'scan-line': 'scanLine 4s linear infinite',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseGlow: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
        ticker: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        scanLine: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
      },
      boxShadow: {
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        'medium': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'large': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
        'terminal': '0 0 0 1px rgba(30, 34, 45, 1), 0 4px 16px rgba(0, 0, 0, 0.4)',
        'glow-cyan': '0 0 20px rgba(0, 212, 255, 0.15)',
        'glow-profit': '0 0 12px rgba(38, 166, 154, 0.25)',
        'glow-loss': '0 0 12px rgba(239, 83, 80, 0.25)',
        'inset-terminal': 'inset 0 1px 0 rgba(255,255,255,0.03), inset 0 -1px 0 rgba(0,0,0,0.3)',
      },
      backgroundImage: {
        'grid-pattern': 'linear-gradient(rgba(30, 34, 45, 0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(30, 34, 45, 0.5) 1px, transparent 1px)',
        'noise': "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E\")",
      },
    },
  },
  plugins: [
    require('daisyui')
  ],
  daisyui: {
    themes: [
      {
        /* Light Theme - Keep unchanged */
        light: {
          "primary": "#3ECF8E",
          "primary-content": "#ffffff",
          "secondary": "#7c3aed",
          "secondary-content": "#ffffff",
          "accent": "#f59e0b",
          "accent-content": "#ffffff",
          "neutral": "#71717a",
          "neutral-content": "#ffffff",
          "base-100": "#ffffff",
          "base-200": "#fafafa",
          "base-300": "#f4f4f5",
          "base-content": "#18181b",
          "info": "#3b82f6",
          "info-content": "#ffffff",
          "success": "#10b981",
          "success-content": "#ffffff",
          "warning": "#f59e0b",
          "warning-content": "#ffffff",
          "error": "#ef4444",
          "error-content": "#ffffff",
        },
        /* Dark Theme - Trading Terminal Style */
        dark: {
          "primary": "#00d4ff",           /* Cyan - Bloomberg terminal accent */
          "primary-content": "#0a0a0c",
          "secondary": "#a78bfa",         /* Soft purple for secondary actions */
          "secondary-content": "#0a0a0c",
          "accent": "#fbbf24",            /* Amber for highlights */
          "accent-content": "#0a0a0c",
          "neutral": "#1e222d",           /* Panel borders */
          "neutral-content": "#d1d4dc",
          "base-100": "#0d0e12",          /* Deepest black - main background */
          "base-200": "#12141a",          /* Slightly lighter - card backgrounds */
          "base-300": "#161922",          /* Panel backgrounds */
          "base-content": "#d1d4dc",      /* Light gray text */
          "info": "#2196f3",              /* Bright blue for info */
          "info-content": "#0a0a0c",
          "success": "#26a69a",           /* Teal green - profit color */
          "success-content": "#0a0a0c",
          "warning": "#ff9800",           /* Orange warning */
          "warning-content": "#0a0a0c",
          "error": "#ef5350",             /* Red - loss color */
          "error-content": "#ffffff",
        },
      },
    ],
  },
}