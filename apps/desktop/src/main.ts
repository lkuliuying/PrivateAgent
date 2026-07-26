import { createApp } from "vue";
import "./design/tokens.css";
import "./design/components.css";
import App from "./App.vue";
import { useAppearance } from "./stores/appearance";

const appearance = useAppearance();
appearance.start();

createApp(App).mount("#app");

if (import.meta.hot) {
  import.meta.hot.dispose(() => appearance.stop());
}
