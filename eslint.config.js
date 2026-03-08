import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import eslintConfigPrettier from "eslint-config-prettier";

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/",
      "**/dist/",
      "**/.expo/",
      "**/android/",
      "**/ios/",
      "**/metro.config.js",
      "apps/agent/",
      "scripts/",
      "apps/mobile/test-preload.ts",
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,

  // Enable typed linting (required by no-unnecessary-condition)
  {
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["eslint.config.js"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },

  // React hooks for mobile app
  {
    files: ["apps/mobile/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },

  // React Native requires require() for static assets
  {
    files: ["apps/mobile/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
    },
  },

  // Turn off rules that conflict with prettier
  eslintConfigPrettier,

  // Project-wide rule overrides
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
    },
  },
);
