import { createRouter, createWebHistory } from "vue-router";
import { session } from "../stores/session";

const routes = [
  { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { public: true, title: "登录" } },
  {
    path: "/",
    component: () => import("../layouts/AppShell.vue"),
    children: [
      { path: "", name: "dashboard", component: () => import("../views/DashboardView.vue"), meta: { title: "总览" } },
      { path: "transactions", name: "transactions", component: () => import("../views/TransactionsView.vue"), meta: { title: "账户流水" } },
      { path: "transfer", name: "transfer", component: () => import("../views/TransferView.vue"), meta: { title: "转账" } },
      { path: "deposits", name: "deposits", component: () => import("../views/DepositsView.vue"), meta: { title: "定期存款" } },
      { path: "confirm/:id?", name: "confirm", component: () => import("../views/ConfirmCenterView.vue"), meta: { title: "确认中心" } },
      { path: "grants", name: "grants", component: () => import("../views/GrantsView.vue"), meta: { title: "助手授权" } },
      { path: "audit", name: "audit", component: () => import("../views/AuditView.vue"), meta: { title: "审计记录" } },
      { path: "demo", name: "demo", component: () => import("../views/DemoView.vue"), meta: { title: "演示控制台" } },
    ],
  },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return { name: "login", query: { redirect: to.fullPath } };
  if (to.name === "login" && session.token) return { name: "dashboard" };
});

router.afterEach((to) => {
  document.title = `${to.meta.title || "澜台"} · 澜台`;
});

export default router;
