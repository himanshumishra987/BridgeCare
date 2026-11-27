import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/** A production bundle must never point at a developer machine. */
const LOOPBACK_HOST = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i;

export default defineConfig(({ command, mode }) => {
  if (command === 'build') {
    const { VITE_API_BASE_URL } = loadEnv(mode, process.cwd(), 'VITE_');
    if (VITE_API_BASE_URL && LOOPBACK_HOST.test(VITE_API_BASE_URL.trim())) {
      throw new Error(
        `VITE_API_BASE_URL is "${VITE_API_BASE_URL}", a loopback host, but this is a production build. ` +
          'Point it at the deployed API origin before building (see .env.production.example).'
      );
    }
    // An unset value is caught at runtime by src/api/client.js, which refuses to
    // fall back to localhost in a production build.
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
    },
  };
});
