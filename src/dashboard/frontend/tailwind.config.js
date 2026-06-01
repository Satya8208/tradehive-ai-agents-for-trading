/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'nut': {
          50: '#fdf8f1',
          100: '#f9eddb',
          200: '#f2d9b6',
          300: '#e9be87',
          400: '#df9d56',
          500: '#d68335',
          600: '#c86a2a',
          700: '#a65225',
          800: '#854224',
          900: '#6c3820',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px #d68335, 0 0 10px #d68335' },
          '100%': { boxShadow: '0 0 20px #d68335, 0 0 30px #d68335' },
        }
      }
    },
  },
  plugins: [],
}
