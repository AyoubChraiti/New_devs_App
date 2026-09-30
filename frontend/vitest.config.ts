import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/components/Dashboard.test.tsx', 'src/lib/secureApi.dashboard.test.ts'],
    clearMocks: true,
  },
});
