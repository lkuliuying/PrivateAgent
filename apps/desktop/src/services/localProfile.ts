import { onScopeDispose, readonly, shallowRef } from "vue";

export interface LocalProfile {
  avatarDataUrl: string;
  nickname: string;
  bio: string;
}

export const LOCAL_PROFILE_KEY = "pa.local-profile.local";
const emptyProfile = (): LocalProfile => ({ avatarDataUrl: "", nickname: "", bio: "" });
const profile = shallowRef<LocalProfile>(emptyProfile());
const readError = shallowRef("");
const avatarPattern = /^data:image\/(?:png|jpeg|webp);base64,/i;

function refresh(): void {
  readError.value = "";
  try {
    const raw = window.localStorage.getItem(LOCAL_PROFILE_KEY);
    if (!raw) {
      profile.value = emptyProfile();
      return;
    }
    const saved: unknown = JSON.parse(raw);
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) throw new Error("invalid_profile");
    const value = saved as Partial<LocalProfile>;
    profile.value = {
      avatarDataUrl: typeof value.avatarDataUrl === "string" && avatarPattern.test(value.avatarDataUrl) ? value.avatarDataUrl : "",
      nickname: typeof value.nickname === "string" ? value.nickname : "",
      bio: typeof value.bio === "string" ? value.bio : "",
    };
  } catch {
    profile.value = emptyProfile();
    readError.value = "无法读取本机资料，原有存储未被修改。";
  }
}

function save(value: LocalProfile): void {
  const next = { avatarDataUrl: value.avatarDataUrl, nickname: value.nickname.trim(), bio: value.bio.trim() };
  if (next.nickname.length > 50 || next.bio.length > 240) throw new Error("个人资料超出长度限制。");
  if (next.avatarDataUrl && !avatarPattern.test(next.avatarDataUrl)) throw new Error("请选择 PNG、JPG 或 WebP 图片。");
  // 写入成功后再更新共享状态，避免保存失败却显示新资料。
  window.localStorage.setItem(LOCAL_PROFILE_KEY, JSON.stringify(next));
  profile.value = next;
  readError.value = "";
}

export function useLocalProfile() {
  refresh();
  const onStorage = (event: StorageEvent) => {
    if (event.key === LOCAL_PROFILE_KEY || event.key === null) refresh();
  };
  window.addEventListener("storage", onStorage);
  onScopeDispose(() => window.removeEventListener("storage", onStorage));
  return { profile: readonly(profile), readError: readonly(readError), save };
}
