<script setup>
import { onMounted, reactive, ref } from "vue";
import { PhPlus, PhMagnifyingGlass, PhTrash, PhPencilSimple, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtTime } from "../utils";

const payees = ref([]);
const form = reactive({ account_no: "", name: "", bank_code: "LANTAI", alias: "" });
const formError = ref("");
const phone = ref("");
const resolved = ref(null);
const resolveError = ref("");
const busy = ref(false);

const load = async () => (payees.value = await api.payees());
onMounted(load);

async function add() {
  formError.value = "";
  if (!form.account_no.trim() || !form.name.trim()) return (formError.value = "请填写账号与户名");
  busy.value = true;
  try {
    const r = await api.addPayee({ ...form, account_no: form.account_no.trim(), name: form.name.trim(), alias: form.alias || undefined });
    toast(r.already_exists ? "该收款人已存在" : "已添加收款人");
    Object.assign(form, { account_no: "", name: "", alias: "" });
    await load();
  } catch (e) {
    formError.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

async function rename(p) {
  const alias = window.prompt("设置备注名（留空清除）", p.alias || "");
  if (alias === null) return;
  try {
    await api.updatePayee(p.id, alias.trim() || null);
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  }
}

async function remove(p) {
  if (!window.confirm(`删除收款人「${p.name}」？历史转账记录不受影响。`)) return;
  try {
    await api.removePayee(p.id);
    toast("已删除");
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  }
}

async function resolve() {
  resolveError.value = "";
  resolved.value = null;
  if (!/^\d{11}$/.test(phone.value)) return (resolveError.value = "请输入 11 位手机号");
  try {
    resolved.value = await api.resolvePhone(phone.value);
  } catch (e) {
    resolveError.value = errorText(e);
  }
}
</script>

<template>
  <PageHeader eyebrow="收款人" title="收款人管理" desc="添加后首次转账仍需短信验证，确保资金流向可核对。" />

  <div class="grid-2" style="align-items: start">
    <form class="panel" novalidate @submit.prevent="add">
      <div class="panel-title"><h3>添加收款人</h3></div>
      <div class="field"><label for="p-no">收款账号</label><input id="p-no" v-model="form.account_no" class="input mono" inputmode="numeric" placeholder="16 位卡号" /></div>
      <div class="field"><label for="p-name">户名</label><input id="p-name" v-model="form.name" class="input" placeholder="与账户实名一致" /></div>
      <div class="field">
        <span id="p-bank" class="label">银行</span>
        <div class="seg" role="group" aria-labelledby="p-bank">
          <button type="button" :aria-pressed="form.bank_code === 'LANTAI'" @click="form.bank_code = 'LANTAI'">澜台</button>
          <button type="button" :aria-pressed="form.bank_code === 'OTHER'" @click="form.bank_code = 'OTHER'">他行</button>
        </div>
      </div>
      <div class="field"><label for="p-alias">备注名（选填）</label><input id="p-alias" v-model="form.alias" class="input" maxlength="32" /></div>
      <p v-if="formError" class="error-text" role="alert" style="margin-bottom: var(--space-3)"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ formError }}</p>
      <button class="btn primary" type="submit" :disabled="busy"><PhPlus :size="20" aria-hidden="true" />添加</button>
    </form>

    <section class="panel">
      <div class="panel-title"><h3>按手机号查询</h3></div>
      <p class="muted" style="margin-bottom: var(--space-3)">仅显示脱敏户名；转账时需输入完整户名核验。查询有频率限制。</p>
      <form class="row" style="align-items: flex-end" @submit.prevent="resolve">
        <div class="field" style="flex: 1; margin: 0"><label for="r-phone">手机号</label><input id="r-phone" v-model="phone" class="input" inputmode="numeric" maxlength="11" /></div>
        <button class="btn" type="submit"><PhMagnifyingGlass :size="20" aria-hidden="true" />查询</button>
      </form>
      <p v-if="resolveError" class="error-text" role="alert" style="margin-top: var(--space-3)"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ resolveError }}</p>
      <dl v-if="resolved" class="kv" style="margin-top: var(--space-4)">
        <dt>手机号</dt><dd class="mono">{{ resolved.phone_masked }}</dd>
        <dt>户名</dt><dd>{{ resolved.name_masked }}</dd>
        <dt>银行</dt><dd>{{ resolved.bank }}</dd>
      </dl>
    </section>
  </div>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="panel-title"><h3>已保存的收款人</h3></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>户名</th><th>备注名</th><th>账号</th><th>银行</th><th>首次转账</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="p in payees" :key="p.id">
            <td>{{ p.name }}</td>
            <td>{{ p.alias || "—" }}</td>
            <td class="mono">{{ p.account_no_masked }}</td>
            <td>{{ p.bank }}</td>
            <td class="num"><span v-if="p.ever_paid">{{ fmtTime(p.first_paid_at) }}</span><span v-else class="tag medium">尚未转账</span></td>
            <td class="row" style="gap: 4px">
              <button class="btn small ghost icon" type="button" :aria-label="`修改 ${p.name} 的备注名`" @click="rename(p)"><PhPencilSimple :size="18" aria-hidden="true" /></button>
              <button class="btn small ghost icon" type="button" :aria-label="`删除 ${p.name}`" @click="remove(p)"><PhTrash :size="18" aria-hidden="true" /></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!payees.length" class="empty">暂无收款人</p>
  </section>
</template>
