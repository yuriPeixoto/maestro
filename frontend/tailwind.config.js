/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          purple: '#7C3AED',
          neon: '#39FF14',
          dark: '#0F172A',
          slate: '#1E293B',
        }
      }
    },
  },
  plugins: [],
}

