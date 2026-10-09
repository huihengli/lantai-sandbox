<script setup>
import { onMounted, ref } from "vue";
import { PhKey, PhCopy, PhCheck, PhProhibit, PhEye, PhPaperPlaneTilt } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtTime } from "../utils";

const grants = ref([]);
const issued = ref(null);
const ttl = ref(1800);
const copied = ref(false);
const busy = ref(false);

const load = async () => (grants.value = await api.grants());
onMounted(load);

async function issue() {
  busy.value = true;
  try {
    issued.value = await api.createGrant(Number(ttl.value));
    copied.value = false;
    toast("已签发 Agent 令牌，仅此一次显示");
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = false;
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(issued.value.agent_token);
    copied.value = true;
  } catch {
    toast("复制失败，请手动选中令牌复制", "warn");
  }
}

async function revoke(g) {
  try {
    await api.revokeGrant(g.grant_id);
    toast("已撤销授权，令牌立即失效");
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  }
}
</script>

<template>
  <PageHeader eyebrow="助手授权" title="智能助手授权" desc="签发一枚受限令牌交给智能助手。您可随时撤销。" />

  <div class="grid-2" style="align-items: start">
    <section class="panel">
      <div class="panel-title"><h3>签发令牌</h3></div>
      <div class="field">
        <label for="g-ttl">有效期</label>
        <select id="g-ttl" v-model="ttl" class="select">
          <option :value="600">10 分钟</option>
          <option :value="1800">30 分钟</option>
          <option :value="3600">60 分钟（上限）</option>
        </select>
      </div>
      <button class="btn primary" type="button" :disabled="busy" @click="issue"><PhKey :size="20" aria-hidden="true" />签发 Agent 令牌</button>

      <div v-if="issued" class="token" role="status">
        <div class="row between"><strong>请立即复制，关闭后无法再次查看</strong>
          <button class="btn small" type="button" @click="copy"><component :is="copied ? PhCheck : PhCopy" :size="16" aria-hidden="true" />{{ copied ? "已复制" : "复制" }}</button>
        </div>
        <code class="tok">{{ issued.agent_token }}</code>
        <p class="hint">权限：{{ issued.scopes.join(" / ") }} · 有效至 {{ fmtTime(issued.expires_at, true) }}</p>
        <p class="hint">使用方式：<code>Authorization: Bearer &lt;令牌&gt;</code>，调用 <code>/api/v1/*</code></p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title"><h3>权限边界</h3></div>
      <ul class="bounds">
        <li class="yes"><PhEye :size="20" aria-hidden="true" /><div><strong>read</strong><br /><span class="muted">查询账户、流水、收款人、定期产品与持有</span></div></li>
        <li class="yes"><PhPaperPlaneTilt :size="20" aria-hidden="true" /><div><strong>prepare</strong><br /><span class="muted">发起转账/定期的“预处理”并取消自己发起的操作</span></div></li>
        <li class="no"><PhProhibit :size="20" aria-hidden="true" /><div><strong>confirm / otp</strong><br /><span class="muted">永不签发。确认与验证码只能由您在用户界面完成；智能助手调用将被拒绝并记入审计。</span></div></li>
      </ul>
    </section>
  </div>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="panel-title"><h3>授权记录</h3></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>编号</th><th>权限</th><th>有效至</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="g in grants" :key="g.grant_id">
            <td class="mono">{{ g.grant_id }}</td>
            <td>{{ g.scopes.join(" / ") }}</td>
            <td class="num">{{ fmtTime(g.expires_at) }}</td>
            <td><span class="tag" :class="g.revoked ? 'muted' : 'ok'">{{ g.revoked ? "已撤销" : "有效" }}</span></td>
            <td><button v-if="!g.revoked" class="btn small danger" type="button" @click="revoke(g)">撤销</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!grants.length" class="empty">尚未签发任何令牌</p>
  </section>
</template>

<style scoped>
.token { margin-top: var(--space-5); padding: var(--space-4); border: 1px dashed var(--c-accent); border-radius: var(--radius-sm); display: flex; flex-direction: column; gap: 10px; background: var(--c-surface-2); }
.tok { display: block; padding: 10px; word-break: break-all; background: var(--c-bg); border-radius: var(--radius-sm); color: var(--c-tech); user-select: all; }
.bounds { display: flex; flex-direction: column; gap: 14px; }
.bounds li { display: flex; gap: 12px; align-items: flex-start; }
.bounds .yes svg { color: var(--c-success); }
.bounds .no svg { color: var(--risk-blocked); }
.bounds svg { flex: none; margin-top: 3px; }
</style>
