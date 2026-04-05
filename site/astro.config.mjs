import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://gspain89.github.io',
  base: '/oracle-openclaw',
  vite: {
    server: {
      fs: { allow: ['..'] }
    }
  }
});
