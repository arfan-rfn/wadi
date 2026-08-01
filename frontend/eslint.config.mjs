import nextConfig from "eslint-config-next";
import coreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextConfig,
  ...coreWebVitals,
  {
    rules: {
      "@next/next/no-html-link-for-pages": "off",
      "react/jsx-key": "off",
      // Allow setState in effect for hydration checks and modal initialization
      "react-hooks/set-state-in-effect": "off",
      // TanStack Table uses functions that can't be memoized
      "react-hooks/incompatible-library": "off",
    },
  },
  {
    ignores: ["dist/*", ".cache", "public/*", "*.esm.js"],
  },
];

export default eslintConfig;
