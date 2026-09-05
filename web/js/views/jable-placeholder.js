import { html } from "../core/dom.js";
import { EmptyState } from "../ui/empty.js";

export default {
  mount(root) {
    root.innerHTML = html`<section id="view-jable" class="view view-jable">
      ${EmptyState({
        iconName: "inbox",
        title: "Jable 模块加载中",
        text: "浏览、筛选与作品详情将在下一阶段接入。可先用顶部输入框解析番号。",
      })}
    </section>`;
  },
  update() {},
  unmount() {},
};
