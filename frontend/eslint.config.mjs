import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextVitals,
  {
    ignores: [".next/**", "next-env.d.ts", "node_modules/**"],
  },
];

export default config;
