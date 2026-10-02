<script setup lang="ts">
import { homeLayout, setHomeLayout, type HomeLayout } from "../services/homeLayout";
import { useNotifications } from "../stores/notifications";
function select(value: HomeLayout) {
  try { setHomeLayout(value); }
  catch { useNotifications().error("首页布局未保存", "本机偏好暂时无法写入，请检查存储空间后重试。"); }
}
</script>
<template>
  <section class="home-layout-settings" aria-labelledby="home-layout-title">
    <h2 id="home-layout-title">首页布局</h2>
    <p>保留项目入口、任务示例和底部输入区。偏好仅保存在本机。</p>
    <div role="radiogroup" aria-label="首页布局">
      <label :class="{ selected: homeLayout === 'standard' }"><input type="radio" name="home-layout" value="standard" :checked="homeLayout === 'standard'" @change="select('standard')" /><span><strong>标准</strong><small>保留当前插画和欢迎区</small></span></label>
      <label :class="{ selected: homeLayout === 'compact' }"><input type="radio" name="home-layout" value="compact" :checked="homeLayout === 'compact'" @change="select('compact')" /><span><strong>紧凑</strong><small>收起插画，使用简短标题区</small></span></label>
    </div>
  </section>
</template>
<style scoped>
.home-layout-settings { margin-bottom: 24px; color: var(--color-fg); }
h2 { margin: 0; font-size: 18px; }
p, small { color: var(--color-fg-muted); line-height: 1.5; font-size: 12px; }
[role="radiogroup"] { display: flex; flex-wrap: wrap; gap: 12px; }
label { display: flex; align-items: center; gap: 10px; min-height: 56px; padding: 12px 16px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); cursor: pointer; }
label.selected { border-color: var(--color-accent); background: var(--color-surface-muted); }
label:focus-within { outline: var(--focus-ring); }
strong, small { display: block; }
strong { font-size: 13px; margin-bottom: 4px; }
</style>
