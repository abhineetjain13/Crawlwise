import nextVitals from "eslint-config-next/core-web-vitals";
import eslintConfigPrettier from "eslint-config-prettier";

const config = [
  ...nextVitals,
  {
    ignores: [".next/**", "next-env.d.ts", "node_modules/**"],
  },
  eslintConfigPrettier,
];

export default config;
