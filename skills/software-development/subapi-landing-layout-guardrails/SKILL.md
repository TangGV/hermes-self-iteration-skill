---
name: subapi-landing-layout-guardrails
description: "SubAPI 公共落地页的结构化 UI 约束：统一 Header/Hero 版心、独立图谱画布、响应式无横向溢出与真实视觉验收。适用于首页、Hero、导航、图谱与营销页布局改造。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [web, react]
metadata:
  hermes:
    tags: [subapi, frontend, landing-page, ui-ux, responsive, design-system]
    related_skills: [design-taste-frontend]
  sources:
    - "nextlevelbuilder/ui-ux-pro-max-skill (MIT): https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"
---

# SubAPI 落地页布局约束

## 目标

让 SubAPI 公共首页保持可信、克制的 B2B 开发者产品表达。优先修复结构与可用性，再做视觉装饰。页面必须由同一套版心、间距 token 和响应式规则控制，不能由各栏各自定位后拼接。

设计取向：编辑化 Swiss / restrained SaaS；`DESIGN_VARIANCE=4`、`MOTION_INTENSITY=2`、`VISUAL_DENSITY=5`。公共首页保持明确的白色主题契约，控制台主题逻辑不得被连带改变。

## 适用场景

- 修改 SubAPI 首页、Hero、顶部导航、模型路由图谱或营销页版式。
- 处理大屏对齐、分栏边界、移动端折叠、横向溢出、首屏层级问题。
- 引入或调整设计 token、CTA、图标按钮、深浅色策略与视觉验收流程。

## 不适用场景

- API、数据库、计费、鉴权、渠道或后台业务逻辑的非视觉改动。
- 控制台的数据表格和管理页面。此类页面应使用其既有产品 UI 规范，不套用营销页规则。

## 不可违反的结构规则

1. **全页只有一套横向坐标系**：Header、Hero、下一节均复用相同的 `--page-max` 与 `--page-pad`。
2. **Header 必须是页面级组件**：Logo 与完整导航在同一个 `.site-header__inner` 中。禁止把导航放进 Hero 右栏或图谱组件。
3. **Hero 必须使用文档流 Grid**：左右栏由 `.hero-inner` 管理；使用 `grid-template-columns: minmax(0, <copy>) minmax(0, 1fr)` 与 `gap` 分隔。
4. **媒体 Grid 项必须显式占满可用宽度**：图谱或媒体外层使用 `justify-self-end` 等自对齐时，必须写 `w-full min-w-0`。否则内部 `w-full max-w-*` 可能按 intrinsic minimum 收缩，页面上只剩近乎不可见的小点。
5. **图谱是独立画布**：网格、SVG/canvas、发光、裁切都属于 `.graph-panel`。图谱不得给 Header、Hero 右栏或页面根节点铺背景。
6. **中线不可作为装饰**：不使用无数据/交互意义的垂直分割线、rail、双 border 或伪元素。左右距离只由 Grid gap 表达。
7. **下一节必须与 Hero 同级**：Hero 后的标题、价值说明、客户证明不能嵌在 `.hero-copy` / `.hero-left` 内。
8. **所有布局先进入正常文档流**：禁止用 `50vw`、固定 left margin、全局 `absolute/fixed` 方式拼 Hero 两栏。

推荐层级：

```tsx
<Page>
  <Header />
  <main>
    <HeroSection>
      <div className="hero-inner">
        <HeroCopy />
        <GraphPanel />
      </div>
    </HeroSection>
    <ValueSection />
  </main>
</Page>
```

推荐 token 骨架：

```css
:root {
  --page-max: 1280px;
  --page-pad: clamp(20px, 4vw, 48px);
  --header-h: 72px;
  --hero-gap: clamp(32px, 5vw, 72px);
}

.site-header__inner,
.hero-inner,
.section-inner {
  width: min(calc(100% - 2 * var(--page-pad)), var(--page-max));
  margin-inline: auto;
}

.hero-inner {
  display: grid;
  grid-template-columns: minmax(0, 520px) minmax(0, 1fr);
  gap: var(--hero-gap);
  align-items: center;
}

.hero-visual { min-width: 0; }
.graph-panel { width: 100%; max-width: 620px; margin-inline-start: auto; }

@media (max-width: 767px) {
  .hero-inner { grid-template-columns: 1fr; }
  .graph-panel { margin-inline: 0; max-width: none; }
}
```

数值可依真实内容调整，但组件层级、共享容器和 Grid 原则不可绕过。

## 首屏与交互规则

- 桌面 H1 最多两行，主 CTA 与次 CTA 必须在首屏可见。
- Hero 仅允许 eyebrow（可选）、标题、lead、CTA 四类文本。功能证明和社会证明放在 Hero 下方。
- 桌面导航单行，默认高度 64-80px。
- 三条证明信息不能做成无差别三等分营销卡。使用有层级的 definition list 或不对称内容编排，且手机端显式堆叠。
- 使用语义 token，禁止在多处组件规则里散落硬编码颜色。
- 图标按钮必须有可访问名称、清晰焦点态与最小 44px 触控面积。
- 动效只用于反馈、状态或叙事。所有非必要动效应尊重 `prefers-reduced-motion`。

## 常见坑

| 错误做法 | 结果 | 正确做法 |
|---|---|---|
| Header 置于 Hero 右栏 | Logo 和导航不共线，导航像长在图谱里 | 独立页面级 Header，共享 `.site-header__inner` |
| 右栏使用 `absolute + 50vw` | 中缝、留白、缩放和移动端失真 | 同一 `.hero-inner` 内用 CSS Grid |
| 网格背景挂在 Hero 右栏 | Header 被视觉污染，图谱没有边界 | 网格背景只挂 `.graph-panel` |
| 下一节标题塞入左 Hero 栏 | 页面节奏断裂，右侧出现空洞 | Hero 与下一节作为同级 section |
| 只看 Build 成功 | 真实页面仍可能裁切、溢出、导航错位 | 必须在真实 URL 的多个视口截图验收 |

## 实施流程

1. 编辑前读组件树与现有 computed layout，确认 Header、Hero copy、graph 和下一节的容器归属。
2. 声明设计取向，保留公开路由、导航文案、登录路径和控制台主题边界。
3. 先修组件层级和共享 token，再处理字号、间距、装饰和动效。
4. 构建、typecheck 和运行与页面相关的测试。
5. 部署到可访问的测试/正式地址后，使用 cache-busting URL 进行真实浏览器验收。

## 验收清单

- [ ] 桌面 1440px：Logo 与导航在同一 Header 线上；Hero copy 和图谱处于同一个 Grid；没有突兀中缝。
- [ ] 桌面 1440px：图谱在 Header 下方是独立画布，下一节拥有独立的全宽 section/container。
- [ ] 1024px：导航单行，Hero 没有重叠或裁切。
- [ ] 768px、375px、320px：`document.documentElement.scrollWidth <= clientWidth`，`document.body.scrollWidth <= clientWidth`。CDP 设备验收必须从 `about:blank` 创建 target，在导航前设置设备尺寸，等待 `Page.loadEventFired` 与首页元素实际渲染后才截图；空白或低字节截图只能作为诊断证据，不能算通过。
- [ ] 小于 768px：Hero 严格单列，图谱位于 copy 之后，证明信息可读地堆叠。
- [ ] 语言、主题、通知、登录等控制具备键盘焦点和可访问名称。
- [ ] 主文案及 CTA 的对比度达到 WCAG AA；首页白色主题和控制台主题均实际测试。
- [ ] 交付报告包含真实 URL、测试视口、截图和构建结果，不以“代码已改/Build 成功”代替视觉验收。

## 安全边界与回滚

- 不修改 URL、一级导航文字、登录行为、追踪事件或控制台主题策略，除非用户明确要求。
- 改动视觉实现前保留现有组件/样式基线；若任一验收视口出现重叠、溢出或主题回归，回退该次布局改动而不是用额外绝对定位补丁掩盖。
- 该 skill 参考 MIT 许可的 `nextlevelbuilder/ui-ux-pro-max-skill` 中的可访问性、响应式、token 与交付检查原则，并结合本项目实际页面边界编写；不复制其样式目录或安装器。