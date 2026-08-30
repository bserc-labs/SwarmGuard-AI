/**
 * Test configuration, kept separate from vite.config.ts.
 *
 * Vitest bundles its own Vite (rollup-based) while the app builds on Vite 8
 * (rolldown-based). Merging the two configs makes TypeScript compare the two
 * incompatible Plugin type trees, so they stay apart. Tests do not need the
 * Tailwind or React plugins — esbuild handles the automatic JSX runtime from
 * the tsconfig `jsx` setting.
 */

import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
