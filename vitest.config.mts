import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    include: ["tests-ts/**/*.test.ts"], environment: "node",
    setupFiles: ["tests-ts/setup.ts"],
    server: { deps: { inline: ["@x402/next"] } },
  },
});
