import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

// 开发时把后端三个前缀代理到澜台后端，避免跨域。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_TARGET || "http://localhost:8001";
  const proxy = Object.fromEntries(["/api", "/ui", "/admin", "/healthz"].map((p) => [p, { target, changeOrigin: true }]));
  return { plugins: [vue()], server: { port: 5172, proxy } };
});
