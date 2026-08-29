import { createApp, type Component } from "vue";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Dropdown,
  Empty,
  Form,
  FormItem,
  Input,
  InputPassword,
  Menu,
  MenuDivider,
  MenuItem,
  Statistic,
  Table,
  TabPane,
  Tabs,
  Tag,
} from "ant-design-vue";
import "./design/tokens.css";
import "./design/components.css";
import RootApp from "./RootApp.vue";
import router from "./router";
import { pinia } from "./stores/pinia";

const app = createApp(RootApp).use(pinia).use(router);
const antComponents: Record<string, Component> = {
  AAlert: Alert,
  AAvatar: Avatar,
  ABadge: Badge,
  AButton: Button,
  ACard: Card,
  AConfigProvider: ConfigProvider,
  ADropdown: Dropdown,
  AEmpty: Empty,
  AForm: Form,
  AFormItem: FormItem,
  AInput: Input,
  AInputPassword: InputPassword,
  AMenu: Menu,
  AMenuDivider: MenuDivider,
  AMenuItem: MenuItem,
  AStatistic: Statistic,
  ATable: Table,
  ATabPane: TabPane,
  ATabs: Tabs,
  ATag: Tag,
};
Object.entries(antComponents).forEach(([name, component]) => {
  app.component(name, component);
});
app.mount("#app");
