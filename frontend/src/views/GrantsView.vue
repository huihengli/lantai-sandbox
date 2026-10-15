<script setup>
import { onMounted, ref } from "vue";
import { PhKey, PhCopy, PhCheck, PhProhibit, PhEye, PhPaperPlaneTilt, PhShieldCheck, PhCursorClick } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtTime } from "../utils";

const grants = ref([]);
const issued = ref(null);
const ttl = ref(1800);
const LONG_TTL = 7 * 24 * 3600;
const copied = ref("");
const busy = ref(false);

const load = async () => (grants.value = await api.grants());
onMounted(load);

async function issue() {
  busy.value = true;
  try {
    issued.value = await api.createGrant(Number(ttl.value), Number(ttl.value) === LONG_TTL);
    copied.value = "";
    toast("已签发 Agent 令牌与确认执行器令牌，仅此一次显示");
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = false;
  }
}

async function copy(key) {
  try {
    await navigator.clipboard.writeText(issued.value[key]);
    copied.value = key;
  } catch {
    toast("复制失败，请手动选中令牌复制", "warn");
  }
}

async function revoke(g) {
  try {
    await api.revokeGrant(g.grant_id);
    toast("已撤销授权，Agent 令牌与执行器令牌立即失效");
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
          <option :value="3600">60 分钟</option>
          <option :value="LONG_TTL">7 天（长期凭证）</option>
        </select>
        <p v-if="Number(ttl) === LONG_TTL" class="hint">长期凭证 7 天内持续有效，泄露风险更高。请妥善保管，不再使用时及时撤销。</p>
      </div>
      <button class="btn primary" type="button" :disabled="busy" @click="issue"><PhKey :size="20" aria-hidden="true" />签发 Agent 令牌</button>

      <div v-if="issued" class="token" role="status">
        <strong>请立即复制，关闭后无法再次查看</strong>
        <div class="row between"><span>Agent 令牌</span>
          <button class="btn small" type="button" @click="copy('agent_token')"><component :is="copied === 'agent_token' ? PhCheck : PhCopy" :size="16" aria-hidden="true" />{{ copied === "agent_token" ? "已复制" : "复制" }}</button>
        </div>
        <code class="tok">{{ issued.agent_token }}</code>
        <p class="hint">权限：{{ issued.scopes.join(" / ") }} · 调用 <code>/api/v1/*</code></p>
        <template v-if="issued.executor_token">
          <div class="row between"><span>确认执行器令牌</span>
            <button class="btn small" type="button" @click="copy('executor_token')"><component :is="copied === 'executor_token' ? PhCheck : PhCopy" :size="16" aria-hidden="true" />{{ copied === "executor_token" ? "已复制" : "复制" }}</button>
          </div>
          <code class="tok">{{ issued.executor_token }}</code>
          <p class="hint">权限：{{ issued.executor_scopes.join(" / ") }} · 只能调用 <code>/api/exec/*</code>。请只交给执行器程序，不要放进大模型的上下文。</p>
        </template>
        <p class="hint">有效至 {{ fmtTime(issued.expires_at, true) }}；两枚令牌属于同一授权，撤销时一起失效。</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title"><h3>权限边界</h3></div>
      <ul class="bounds">
        <li class="yes"><PhEye :size="20" aria-hidden="true" /><div><strong>read</strong><br /><span class="muted">查询账户、流水、收款人、定期产品与持有</span></div></li>
        <li class="yes"><PhPaperPlaneTilt :size="20" aria-hidden="true" /><div><strong>prepare</strong><br /><span class="muted">发起转账/定期的“预处理”并取消自己发起的操作</span></div></li>
        <li class="yes"><PhShieldCheck :size="20" aria-hidden="true" /><div><strong>protect</strong><br /><span class="muted">仅限“收紧”类直接操作：冻结卡片、关闭交易开关、调低额度。挂失与放宽类（解冻、提额、开境外）仍需您确认。</span></div></li>
        <li class="yes"><PhCursorClick :size="20" aria-hidden="true" /><div><strong>confirm / otp（仅确认执行器）</strong><br /><span class="muted">只发给确认执行器令牌：执行器弹出确认框，由您手动确认（必要时输入验证码）后才执行。智能助手令牌本身没有确认权。</span></div></li>
        <li class="no"><PhProhibit :size="20" aria-hidden="true" /><div><strong>grant</strong><br /><span class="muted">永不签发。签发与撤销授权只能由您在用户界面完成。</span></div></li>
      </ul>
    </section>
  </div>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="panel-title"><h3>授权记录</h3></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>编号</th><th>权限</th><th>确认执行器</th><th>有效至</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="g in grants" :key="g.grant_id">
            <td class="mono">{{ g.grant_id }}</td>
            <td>{{ g.scopes.join(" / ") }}</td>
            <td>{{ g.executor ? "已绑定" : "—" }}</td>
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
