import { ref, type Ref } from "vue";
import { getHealth } from "../api";

export interface ComponentHealth {
  ok: boolean;
  error?: string;
  [key: string]: unknown;
}

export interface HealthSnapshot {
  api: ComponentHealth;
  mysql: ComponentHealth;
  chroma: ComponentHealth & { collections?: number };
}

export interface HealthStore {
  health: Ref<HealthSnapshot | null>;
  refreshing: Ref<boolean>;
  error: Ref<string>;
  refresh: () => Promise<HealthSnapshot | null>;
}

export function createHealthStore(
  fetchHealth: () => Promise<Record<string, unknown>> = getHealth
): HealthStore {
  const health = ref<HealthSnapshot | null>(null);
  const refreshing = ref(false);
  const error = ref("");
  let inflight: Promise<HealthSnapshot | null> | null = null;

  async function refresh(): Promise<HealthSnapshot | null> {
    if (inflight) return inflight;

    refreshing.value = true;
    inflight = (async () => {
      try {
        const next = (await fetchHealth()) as unknown as HealthSnapshot;
        health.value = next;
        error.value = "";
        return next;
      } catch (cause) {
        // Keep the last confirmed snapshot during refresh failures. Consumers
        // can disclose the error without flashing every service card red.
        error.value = cause instanceof Error ? cause.message : String(cause);
        return health.value;
      } finally {
        refreshing.value = false;
        inflight = null;
      }
    })();

    return inflight;
  }

  return { health, refreshing, error, refresh };
}

const healthStore = createHealthStore();

export function useHealth(): HealthStore {
  return healthStore;
}
