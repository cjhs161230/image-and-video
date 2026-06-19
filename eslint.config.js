import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: ["node_modules/**", "data/**", "playwright-report/**", "test-results/**"],
  },
  js.configs.recommended,
  {
    files: ["frontend/**/*.js", "tests/e2e/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
];
