import { ref, readonly } from "vue";
export type HomeLayout = "standard" | "compact";
const key = "pa_home_layout_v1";
function load(): HomeLayout {
  try { return localStorage.getItem(key) === "compact" ? "compact" : "standard"; }
  catch { return "standard"; }
}
const current = ref<HomeLayout>(load());
export const homeLayout = readonly(current);
export function setHomeLayout(value: HomeLayout): void {
  localStorage.setItem(key, value);
  current.value = value;
}
