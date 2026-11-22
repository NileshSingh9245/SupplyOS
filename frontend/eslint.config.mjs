import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default [
  { ignores: [".next/**", ".runtime/**", "node_modules/**", "next-env.d.ts"] },
  ...nextVitals,
  ...nextTypescript,
  { files: ["**/*.js", "**/*.cjs"], rules: { "@typescript-eslint/no-require-imports": "off" } },
];
