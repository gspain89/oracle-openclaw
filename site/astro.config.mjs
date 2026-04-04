import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://gregyh.github.io',
  base: '/oracle-openclaw',
  vite: {
    server: {
      fs: { allow: ['..'] }
    }
  }
});
