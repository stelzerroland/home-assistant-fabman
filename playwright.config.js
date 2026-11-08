import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/frontend',
  fullyParallel: true,
  use: { viewport: { width: 390, height: 844 } },
});
