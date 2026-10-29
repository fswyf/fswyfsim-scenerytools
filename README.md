# BGL 机场反编译器 v1.4.1

把 **MSFS / FSX 机场 BGL** 反编译成 **BGLComp 风格 XML**（跑道、跑道入口、COM 频率、滑行道点、
滑行道路径、机位、停机坪、画线、边灯、景物对象、进近程序、地面矢量 CVX）。三种形态：
**Windows EXE（图形界面 / 命令行）** 与 **网页版**。

> 输出 XML **不含任何注释**，只有 `<?xml?>` 声明和数据元素。
>
> 在线使用（浏览器本地解析，文件不上传）：<https://fswyfsim-scenerytools.pages.dev/>
> 源码与桌面版下载：<https://github.com/fswyf/fswyfsim-scenerytools>

## 版本 1.4.1 新增

- **机场标识（`ident`）修正**：机场记录的 ICAO 标识是压缩 ICAO 字段，位置与位移随记录版本不同 ——
  `0x0113`（2024）在 `+76`、位移 6；`0x0056`（2020/FSX 版式）在 `+40`、位移 5。
  旧实现一律按「`+76` / 位移 5」读，2024 记录会多解出一位前导无效字符（`ZSFZ` 被读成 `6ZKXY`、`ZWWW` 读成 `6ZTTS`）。
  修正后与 BGL 文件内登记的四字机场代码一致，网页版同步。

## 版本 1.4.0 新增

本次是**解码覆盖面**的一次大补：把「已解出但没写进 XML」和「根本没解」的记录一次性补齐，并让
输出与对照输出在同一份 BGL 上做到**逐元素、逐属性一致**。

- **分组（`<Group>`）体系**：以前只发两个占位组，现在按对照解析程序的规则完整复现：
  景物对象按库对象 GUID 分到 7 个顶层组（`Buildings` / `Exclusion` / `Lights` / `Other Models` /
  `ParkingSigns` / `Static Jetways` / `Terrain`），机场自身为第 8 组（`groupIndex="7"`），
  机场内部再分 13 个子组（跑道、跑道标线、画线、地面、中线、滑行道、机位、滑行道路径、
  边线、跑道警报灯、中线灯、边灯、滑行道牌），并按元素类别自动计算 `parentGroupID` / `groupIndex`。
  停机坪按「局部 UV / 优先级 / 表面材质」细分为地面、跑道标线、画线三类；画线按类型、描边类型、
  表面材质细分为中线、边线、跑道标线；边灯按预设名细分为跑道警报灯、中线灯、边灯。
- **NDB（`0x0106`）**：导航段里的 NDB 记录，输出 `<Ndb>`（类型、频率、范围、磁差、区域、识别码、名称）。
- **VDGS（`0x0104`）**：目视停靠引导系统记录，输出 `<VDGS gateName parkingNumber suffix>`，
  其内嵌的场景对象一并还原（`containerTitle="VDGS_01"` 之类）。
- **Services / Fuel**：机场头的燃油位图，输出 14 条 `<Fuel type availability>`（每种油两位：
  可用 / 需申请）；位图为 0 时整段不输出。
- **2024 进近程序（`0x0111` / `0x0110`）**：`<Approach>`、`<Transition>`、
  `<ApproachLegs>` / `<MissedApproachLegs>` / `<TransitionLegs>` 全量解出，含 2024 的 96 字节腿格式、
  `rho` / `course` / `distance` 的官方格式规则（`0`、`%dM`、`%dN` 与最短往返浮点）。
- **Jetway（`0xDE`）**：一个机位廊桥可内嵌 1~2 个场景对象（`SimObject` 或 `LibraryObject`），
  现在逐条还原，不再只取第一个。
- **属性纠错**：`TextMarking`（文字标记）整体偏移错位并多出四个不存在的属性，现已按真实布局重写；
  `TaxiwayPath` 的 `centerLine` 不再写死 `FALSE`；`TaxiwayParking` 支持变长条目并输出 `airlineCodes`；
  `Runway` 的起飞 / 着陆 / 航线标志位不再写死；`Tower` 的 `overrideSize` 与高度按 float32 量化输出；
  `VectorPlacement` 的 `rotation` 是 32 位整数（`112/624` 显示为 `Follow edge`）；
  `TaxiwayPoint` 的类型表按官方枚举修正；机场 `ident` 取机场记录自身字段（不再用机场摘要里的 ICAO），
  `magvar` 取机场头的磁差，并去掉此前拼凑出来的 `region/country/state/city`。
- **一致性**：ZSFZ 与对照输出**完全一致**（10024 个元素，0 差异）；ZWWW 55511 个元素仅剩 4 个
  `Windsock` 差异 —— 那是对照解析程序自身在该记录上读错偏移（它输出 `poleHeight="1083330.0M"`），
  本工具输出真实的 `15.000000` / `9.000000`，属**已知且有意保留**的差异。
- **网页版同步**：`web/bgl2xml.js` 与 Python 版功能对齐，六个社区机场交叉验证（Python vs 网页）
  逐元素一致。

## 版本 1.3.6 新增

- **WasmModule（`0x0102`）**：2024 机场里的 WASM 模块记录，载荷是单个 NUL 填充的相对路径串，
  输出为 `<WasmModule name="…"/>`（仅在 2024 档输出，2020 schema 无此元素）。
- **机场标识**：优先用机场摘要记录（`0x2C`）里的识别码；文件里没有该记录时，仍按源文件名
  （去掉扩展名、转大写）输出，不额外造值 —— 若长度超过 schema 的 `stString5`/`stString8`，
  可用命令行 `--ident=` 或界面里的识别码输入框覆盖。
- **`forceElevation` 仅 2024**：2020 的 `ctRunway` 没有该属性，2020 档不再输出（否则 2020 编译会报错）。
- **跑道形变负零**：`RunwayDeformation` 的 `corner`/`normal` 数值统一按最短往返格式化，
  `-0` 输出为 `-0.0`（与 2024/2020 schema 的 `xs:double` 表现一致）。

## 版本 1.3.5 新增

- **文档与注释清理**：不记录任何具体反编译程序的名称，改按其功能称「对照解析程序」（把同一 BGL 解析成 XML 用于交叉校验的程序，非官方），其输出称「对照输出」。
  验证口径保持两条可独立复现的硬指标：① 生成的 XML 能通过官方 `bglcomp.xsd` 校验
  （2020 档用 `C:\MSFS SDK\Tools\bin\bglcomp.xsd`，2024 档用 `C:\MSFS 2024 SDK\Tools\bin\bglcomp.xsd`）；
  ② 有作者源工程 XML 的机场（如 ZLIC、ZGBH）直接与源工程逐属性比对。
  功能与输出**没有任何变化**（生成的 XML 逐字节不变），仅措辞与归因变更。

## 版本 1.3.4 新增

- **`0x118` 结构化解析**：福州长乐那条 658 字节记录 = `u16 顶点数(32) | 16 字节 GUID | 32 × (lat f64, lon f64, f32)`，
  GUID `{470F9B8F-4572-4F10-A3B3-6AB2C278ED03}`（全文件唯一）。
  2024 schema 里唯一的顶点类型 `ctVertexLL` 只有 `lat/lon/spline`，装不下每顶点的第 4 列 f32，
  唯一带 GUID 的顶点元素 `ctVectorPlacement` 也没有逐顶点字段；对照解析程序同样不处理该记录（对照输出的
  ZSFZ.xml 里没有任何对应几何）⇒ 本工具改为**把它写进摘要与错误报告的「已解码但未写入 XML」段**
  （GUID、顶点数、经纬包围盒、第 4 列范围），不再列进「未解码记录」。
  实测该 32 个顶点是散布在约 700×500 m 内的若干短线段（相互独立、非单一多边形边界）。

## 版本 1.3.3 新增

- **`0x0056` 子记录解出**：它是「投影网格重复表」——90 字节头 + N 条 `id 0xE8 / 80 字节`
  子记录，每条子记录载荷与同名 `0xE8` 记录**逐字节相同**（ZSQD：813 条，与 813 条 `0xE8` 一一对应）。
  对照输出对两者都输出 `<ProjectedMesh>`，所以本次也让 `0x56` 走同一套 `_pm_add()`，
  青岛胶东的 `<ProjectedMesh>` 从 813 条补齐到 **1626 条，与对照解析程序逐属性一致**；
  表尾的 8 字节 `0x00D4` 终止标记不再计入未解码。
- README 未解码清单相应移除 `0x56`。

## 版本 1.3.2 新增

- **一键导出错误报告**（GUI 按钮 / 网页按钮 / 命令行 `--report`）：纯文本报告，含
  工具版本与运行环境、生成时间、源文件路径 / 大小 / 修改时间 / 校验值
  （命令行与 GUI 用 SHA-256，网页版用 MD5，浏览器里同步算法更省时）、输出文件名与大小、
  机场摘要、**子记录统计**（每条子记录 id 的出现次数，降序）、
  **未解码记录明细**（每条附 32 字节载荷样例）。
  - GUI：底部「导出错误报告」按钮 → 选保存位置（多个文件合并成一份，逐个分段）
  - 命令行：`bgl2xml-cli.exe X.bgl --report` → `X_report.txt`；`--report=D:\out.txt` 可指定路径
  - 网页版：BGL 标签页「导出错误报告」→ 单文件时下载 `X_report.txt`（与命令行同名规则），
    多文件合并为 `bgl2xml_report.txt`；
    XML 转换标签页「导出转换报告」→ 下载 `msfs_toolbox_xml_report.txt`（含命中/未命中的清理规则）

## 版本 1.3.1 新增

- **机场 `region` / `country` / `state` / `city` 修正**：名称表（section 0x27）分组偏移不总是对齐
  （如 ZSQD 会解出 `region="Asia" country="Shandong" state="Qingdao"` 这种错位串），现在先按分组索引取，
  分组不可靠时按「区域 / 国家 / 省 / 市 / 机场名」的字符串存放顺序兜底 —— ZSQD 输出
  `region="Asia" country="China" state="Shandong" city="Qingdao"`，与对照解析程序完全一致；其余机场不受影响。
- **跑道材质子记录 0xCB 的元素名修正**：官方 schema 里该元素叫 `<Material>`（类型 `ctFacilityMaterial`），
  不是 `<FacilityMaterial>`；且 `guid` / `type` / `tilingU` / `tilingV` 四个属性必填。
  旧写法在 2020 与 2024 两版 schema 下都非法，现在按 `<Material guid="…" type="…" tilingU="…" tilingV="…" width="…" falloff="…"/>` 输出。
- **CVX `<Polygon version="0.4.0">` 只在 2024 档输出**：2020 schema 的 `ctPolygon` 没有 `version` 属性。
- **2024 航路点（section 0x22 记录 id 0x108，36 字节）**：`waypointIdent` 改用 `icao_2024()` 解码、
  `waypointRegion` 取 `u32@28 & 2047`。ZWWW 53 条航路点的识别码/区域与对照解析程序逐条一致
  （此前解出 `66 2HA` 这类含空格串，2020 schema 直接校验失败）。
- **11 个机场 × 双档共 22 个输出全部通过各自 schema 校验**（见第六节表格）。

## 版本 1.3.0 新增

- **离场程序 `<Departure>`（子记录 0x42）与进场程序 `<Arrival>`（子记录 0x48）**：名称取自载荷
  +6 的 8 字节字符串；子容器按对照解析程序顺序输出 —— 离场为 `RunwayTransitions` → `CommonRouteLegs` →
  `EnrouteTransitions`，进场为 `EnrouteTransitions` → `CommonRouteLegs` → `RunwayTransitions`。
  `RunwayTransitionLegs` 带 `number` / `designator`（取自容器的跑道号与方位字节），
  `EnrouteTransitionLegs` 带可选 `name`；腿（`<Leg>`）沿用进近程序的全套属性与格式化规则。
  同时支持 FS9/FS20（腿 60/72 字节）与 2024（腿 96 字节）三种步长。
- **2024 灯柱 `<MastLight>`**（子记录 0xFB，54 字节）：经纬度（14 位小数）与 heading 取自载荷
  `u32@6 / u32@10 / f32@26`；每机场 2–3 条，位置落在跑道延长线 / 道口附近（ZSSS 3 条、VHHH 2 条）。
  该记录的元素归属尚未取得对照解析程序真值，按 `<MastLight>` 输出属**推测映射**（载荷里另有
  `u16@14`（ZSSS 3080/3082、VHHH 2784/2782）、两个 ≈35 的浮点、尾部 `0x00 0xFF 0x0F 0x00`
  等字段暂无对应属性）。2020 档不输出（2020 schema 没有 MastLight）。
- **健壮性**：`0x22` 航路点 section 里不足 28 字节的记录不再越界崩溃，改为计入未解码清单；
  `<Tower>`（无内嵌景物对象那种）的 `overrideLevel` 改取载荷字节 3，与对照解析程序一致。

## 版本 1.2.1 新增

- **2024 地面文字 `<TextMarking>`**（子记录 0xFF，114 字节）：经纬度、heading、scale、letterSpacing、
  lineSpacing、paddingX / paddingY、outlineThickness、drawBackground / drawOutline / center，
  `label` 取载荷尾部 64 字节 NUL 结尾 UTF-8，三组颜色→`<ColorText>` / `<ColorBackground>` /
  `<ColorOutline>`（全零不输出）。2020 档不输出（该元素 2020 schema 没有）。

## 版本 1.2.0 新增

- **机场要素补全**：`<Airport>` 的 displayName / region / country / state / city / name / ident（取自
  0x2C 机场摘要并按 base-38 解码）、`alt` 14 位精度、`magvar`、`applyFlatten`、`starAirport`、
  `groundMergingTransfertBright/Dark`（子记录 0xE9）。
- **精度对齐对照解析程序**：经纬度、海拔、顶点一律 14 位小数（`{:.14f}`），海拔保留对照解析程序的双重 f32 舍入。
- **进近程序**：子记录 0xFA 及其 0xF4/0xF5/0xF6 容器 → `<Approach>` / `<ApproachLegs>` /
  `<MissedApproachLegs>` / `<Transition>` / `<TransitionLegs>` / `<Leg>`，含各腿型专属属性
  （高度、航向、距离、速度、飞越、转弯方向、垂直角等）与对照解析程序格式化规则。
- **停机坪**：补齐 groundMerging / excludeVegetation* / opacity / tiling / heading / falloff /
  offsetU / offsetV / isRectangle（平行四边形判定按对照解析程序容差 0.05 实现）。
- **机位**：对照解析程序位域解包（名称 5 位、类型、机位号 12 位）、`suffix` 取载荷字节 37 查 PARKING_NAME
  （落到 `PARKING/N_PARKING` 等非 GATE 名称时，Schema 的 stParkingSuffix 无此写法，统一降级 NONE 并计数）、
  numberMarking / has3DMesh / numberBiasX / numberBiasZ / numberHeading。
- **跑道与入口**：`transparent`、`groundMerging`、`excludeVegetationAround`、`patternAltitude`、
  主副端 markingBias；`<RunwayStart end>` 改为按“号 + 方位”与跑道主/次端匹配后判定。
- **滑行道路径**：centerLineLighted、enhanced、designator、groundMerging、excludeVegetation*、
  weightLimit（真实值，不再固定 0）。
- **其他**：ILS/DME/下滑台按跑道挂接、地面矢量 CVX（多边形/线段/矩形）、ExclusionRectangle、
  航路点与地标、SceneryObject 姿态补全、`<AirportArchetype>` 的 `<ParamOverride>` 参数覆盖
  （子记录 0x5C，见下节）、2024 版 `<TextMarking>` 地面文字（子记录 0xFF，含 `<ColorText>` /
  `<ColorBackground>` / `<ColorOutline>` 三个子元素与 label，2020 档不输出）、
  机场级 `<Start>`（type 为 0 时省略该属性，因 stStart 只有
  TRACK/RUNWAY/HELIPAD/WATER 四值）。
- **只生成两个分组**：机场自身是组 1，其下声明
  `<Group displayName="Ground" parentGroupID="1" groupID="2">` 与
  `<Group displayName="Model" parentGroupID="1" groupID="3">`（与对照解析程序/编辑器产出的"机场组 + 子组"结构一致）。
  三维模型/景物（`<SceneryObject>` 及库对象、`<SimObject>`、风向袋、`<ProjectedMesh>`、`<Jetway>`、
  `<Tower>`、`<VectorPlacement>`）挂 **Model(3)**；其余（跑道、入口、滑行道点/路径、机位、停机坪、
  画线、网格填充画线、边灯、灯支座、标志牌、直升机坪、CVX 多边形/矩形）挂 **Ground(2)**，
  `groupIndex` 在各自组内从 1 递增。
- **2024 档案校准**（用对照解析程序对同一个 ZSFZ.bgl 的输出做真值）：`<Markings>` 的
  leadingZeroIdent / alternatePrecision / noThresholdEndArrows 取自跑道记录灯光字节的 bit6/5/7；
  2024 版 Ils 的 `ident` 走`icao_2024`（可能整体加了 2²⁶）；`<Airport>` 的
  trafficScalar / applyFlatten / isOnTIN / starAirport 改为读记录位；画线在机场记录为 `0x0113`
  时输出 `outlineType`（2024 profile）；`0xFC` 航司代码表解码并在摘要里报出。

## 一、EXE 图形界面版

```
dist\BGLAirportDecompiler.exe
```
1. 双击打开 → 「添加文件…」或「添加文件夹…」选中 `.bgl`（可多选）
2. 需要时填「识别码覆盖」（留空则用文件名，如 `ZGBH.bgl` → `ident="ZGBH"`）
3. **一键 BGL → MSFS 2020**：勾选「反编译为 MSFS2020」（EdgeLights 用 preset 并包在 `<ApronEdgeLights>` 里、PaintedLine 不带 width、Windsock 不带颜色），一次性产出可直接给 MSFS 2020 用的 XML
4. 点「开始反编译」→ XML 输出到 BGL 同目录、同名（2020 模式为 `<名字>_MSFS2020.xml`）

图形界面版也认命令行参数（带参数时不弹窗，直接跑）：

```
dist\BGLAirportDecompiler.exe <文件.bgl> [输出.xml] [--ident=ZGBH] [--msfs2020] [--quiet] [--report]
```

## 二、EXE 命令行版

```
dist\bgl2xml-cli.exe  <文件.bgl> [输出.xml] [--ident=ZGBH] [--msfs2020] [--quiet] [--report[=报告.txt]]

:: 例：输出到同目录同名 XML
dist\bgl2xml-cli.exe "D:\MSFS2024\Community\roy-airport-zgbh\Scenery\airport-zgbh\scenery\ZGBH.bgl"

:: 例：一键 BGL → MSFS 2020（输出同名 _MSFS2020.xml）
dist\bgl2xml-cli.exe "…\ZGBH.bgl" --msfs2020

:: 例：批量（支持通配符）
dist\bgl2xml-cli.exe "D:\scenery\*.bgl" --quiet

:: 例：额外导出诊断报告（默认 <输出名>_report.txt）
dist\bgl2xml-cli.exe "…\ZGBH.bgl" --report
```
退出码：0 成功、2 参数/文件错误、3 不是可识别的机场 BGL。

## 三、网页版（离线单页）

```
web\index.html      ← 双击即可用（浏览器本地解析，文件不上传）
web\bgl2xml.js      ← 解析核心（浏览器 / Node 通用）
```

> 整合版在 **`MSFS_Toolbox\`**：一个页面两个标签页 ——「MSFS XML 转换 2024 → 2020」+「机场 BGL 反编译」，
> 同样只需 `index.html` + `bgl2xml.js` 两个文件，功能与本目录下的独立页一致。
> 标签页 1（XML 转换）选好文件 → 「开始转换」→ 也会给每个文件一份**机场摘要卡片**
> （机场/跑道/跑道入口/滑行道点/滑行道路径/机位/停机坪/画线/边灯/景物对象/清理项），
> 下方另附该文件命中的清理规则明细，最后用「下载转换结果」保存。
> 标签页 2 拖放 `.bgl`（可多个）→ 勾选「反编译为 MSFS2020」可一键出 2020 版 → 「开始反编译」→
> 每个机场各显示一份摘要（机场/跑道/滑行道点/滑行道路径/机位/停机坪/画线/边灯/景物对象/未解码记录），
> 日志区给出逐文件结果，最后用「下载全部 XML」一次性保存。
可直接放进任意静态站点（例如 `fswyf-site\` 下新建一个 `bgl2xml\` 目录，把这两个文件放进去），
也不依赖任何第三方库或服务器。

**部署到 Cloudflare（Pages / Workers）**：见 [`deploy-cloudflare.md`](deploy-cloudflare.md)——
上传 `web\` 里这 2 个文件即可，无需构建命令；两个 exe 也都在 Pages 单文件 25 MiB 限制之内，可以一并挂下载。

## 四、自己重新构建 EXE

```
build_exe.bat
```
脚本会检查/安装 PyInstaller，然后用 `--onefile` 分别构建图形版与命令行版到 `dist\`。
需要 Windows + Python 3.10+。源码在 `src\`：

| 文件 | 作用 |
|---|---|
| `src\bgl2xml_core.py` | 解析核心（容器、机场记录、各子记录、景物对象），无第三方依赖 |
| `src\gui_app.py` | tkinter 图形界面；带参数时走命令行 |
| `src\cli.py` | 命令行入口（设置控制台 UTF-8） |

## 五、格式说明（逆向所得）

```
文件头 0x38 字节: magic 0x19920201 | 0x38 | 0 | 0 | magic2 0x08051803 @+0x10 | section 数 @+0x14
section 表: 20 字节/条  (类型, 标志, 子块数, 目录偏移, 目录大小)
子块目录  : 16 字节/条  (id, 记录数, 数据偏移, 数据大小)
机场记录 (section 类型 0x03)：两种写法，区别只在子记录链起点
  id 0x0113（新）: +0x5C 起为子记录流
  id 0x0056（FSX 系）: +0x44 起为子记录流
  +0 u16 id | +2 u32 长度 | +6 六个 u8 计数 | +12 u32 经度 | +16 u32 纬度 | +20 i32 海拔(mm)
  子记录流: (u16 id, u32 size) + 载荷，一路走到记录尾
坐标定标: lon = raw*360/(3*2^28) - 180 ; lat = 90 - raw*180/2^29 ; 航向 = raw*360/2^32

已解码子记录: 0x19 机场名 | 0xCE 跑道 | 0x11/0x6A 跑道入口 | 0x11A COM | 0x12 COM（另一种写法）| 0x1A 滑行道点
              0xD4 滑行道路径 | 0xE7 机位 | 0xD0 停机坪 | 0xCF 画线 | 0xD8/0x113 网格填充画线
              0x31 停机坪边灯 | 0xD9 滑行道牌 | 0x57 灯光支座 | 0xDE 登机桥 | 0x5A 矢量围栏
              0xE8 投影网格 | 0x58 灯光预设 LightPreset | 0x59 预设里的灯 Light | 0x33 DeleteAirport
              0x66 塔台 Tower（内嵌景物对象或默认经纬高）| 0x26 直升机坪 Helipad | 0x5D 机场 archetype
画线/网格填充画线的类型码表与 COM/表面/坪型枚举取自FSTypes 枚举（见根目录 ）
跑道内部还解出: 0x3E 跑道形变 | 0x0B/0x0D Vasi | 0xDF/0xE0 进近灯 | 0x06 偏移阈值
                 基记录 +0x2A 标记位域 → <Markings>、+0x2C 灯光字节 → <Lights>、+0x28 patternAltitude
结构注意：停机坪要包在 <Aprons> 里、画线与网格填充画线要包在 <PaintedElements> 里、
          投影网格 <ProjectedMesh> 在 <Airport> 内部（2020/2024 的 bglcomp.xsd 都是这个结构）
机场元数据 (section 0x35): 区域/国家/省/市/名称 字符串表
景物对象 (section 0x25): (u16 id, u16 size) 记录，经纬度 @+4/+8、海拔 @+12、航向 u16@+22
  id 0x0B size 64/92 库对象(GUID@+44, scale@+60) | id 0x19 容器对象(scale@+44, 名称@+52) | id 0x18 风向袋
输出统一做 XML 转义（滑行道牌等文本里会出现 < > &）
```

## 六、准确性验证（可复现）

| 验证项 | 方法 | 结果 |
|---|---|---|
| 机位字段布局 | `ZSFZ.bgl ↔ ZSFZ.xml` 真值配对（59 个机位） | 半径/朝向/经纬度 **59/59 一致** |
| 滑行道路径布局 | 同上（560 条路径） | start/end/width/surface **560/560 一致** |
| 机位号与类型打包 | 同上 | `packed = 名称 \| 类型<<8 \| 机位号<<12` **59/59 一致** |
| 滑行道点类型 | 同上（384 个点） | flag 1=NORMAL、5=HOLD_SHORT_NO_DRAW **384/384 一致** |
| 全要素清单 | 用本工具反编译 `ZSFZ.bgl`，与对照输出的 XML 比元素 | Runway/RunwayStart/TaxiwayPoint/TaxiwayPath/TaxiwayParking/Apron/PaintedLine/EdgeLights/Vertex **全部一致（含 8064 顶点）** |
| 景物对象 | 与既有反编译结果（402 个 GUID）逐一对位 | 经纬度/航向 **最大误差 0.001 m** |
| 跑道 | 与 X-Plane Scenery Gateway 的 ZGBH 数据比对 | 01/19、45 m 宽，两端差 ~10 m |
| 三种形态一致性 | Python / EXE / JS 输出逐元素比对 | 元素数 2570，**属性差异 0** |
| FSX 系机场记录（0x0056） | `kmbase.bgl ↔ kmbase.xml`（对照输出，ZPPP 昆明长水） | 全部元素计数一致；路径 2007×4、机位 175×5、点位 1544×2、登机桥 106×3 **超差 0** |
| 大场景景物对象 | 同上，3013 个对象按坐标配对 | 坐标/航向/scale **3013/3013 一致**，GUID **3000/3000 一致** |
| Python/JS 逐字节一致 | kmbase/ZGBH/ZSFZ × (2020/2024) 六格 | **6/6 逐字节相同**（数字格式化同为半数取偶） |
| 与对照解析程序属性级一致 | ZPPP / ZSWX / ZBAA 逐标签属性多重集比对 | 元素与属性除分组外与对照解析程序一致：ZSWX、ZBAA **零差异**；ZPPP 仅风向袋 5 处（对照解析程序读的是未初始化内存，值为 1083330.0M，本工具输出真实值 15/9）。对照输出每文件另有 20 个 `<Group>` 声明（FSData 7 + Airport 13），本工具按需改为 **Ground / Model 两个组** |
| 分组 | 所有输出 | 恰好 2 个 `<Group>`；每个可分组元素带 `parentGroupID`（1=Ground / 2=Model）与组内递增的 `groupIndex`；无重复属性、XML 良构 |
| 2024 档案（ZSFZ） | 与对照解析程序对同一 BGL 的输出比对（2020 profile） | 修掉 4 处真 bug 后，只剩两处**刻意保留**：`ident` 对照输出乱码 `6ZKXY`（真值 ZSFZ）、`region/country/state/city` 对照解析程序缺失（本工具给出 ASIA/CHINA/FUJIAN/FUZHOUCHANGLER）；`outlineType` 2020 profile 不输出（2020 版 xsd 无此属性） |
| 2024 地面文字（ZLIC） | 本工具与 `ZLIC.xml` 源工程（14 条 `<TextMarking>`）逐字段比对 | heading/scale/间距/边距/描边/三个开关/标签/三组颜色（42 个 `<ColorText>` 等）**全部一致**；坐标差 ≤2 cm（BGL 里是定标整数，源 XML 是双精度，编译时已量化）；三个开关的位序用 14 条样本反查确认为 bit0=drawBackground / bit1=drawOutline / bit2=center |
| 2020 / 2024 schema 合规 | 十一个机场 × 双档共 **22** 个输出（kmbase / ZGBH / ZBAA / ZSWX / ZSFZ / ZLIC / ZSSS / ZSQD / ZYHB / ZSWY / ZWWW），分别对 `C:\MSFS SDK\`、`C:\MSFS 2024 SDK\` 的 `bglcomp.xsd` 做 XSD 校验 | **22/22 通过，0 错误** |
| 2024 航路点（ZWWW） | 本工具与对照解析程序对同一 BGL 的输出逐条比对（53 条 `<Waypoint>`） | `waypointIdent` / `waypointRegion` **53/53 一致** |
| 机场区域/国家/省/市（ZSQD） | 本工具与对照解析程序对同一 BGL 的输出比对 | `region=Asia / country=China / state=Shandong / city=Qingdao` **完全一致** |
| `0x0056` 投影网格重复表（ZSQD） | 本工具与对照解析程序对同一 BGL 的输出比对（`<ProjectedMesh>` 条数与属性多重集） | **1626 = 1626，属性多重集一致** |
| EXE 与 Python 一致 | `bgl2xml-cli.exe` vs `cli.py`（ZGBH / ZWWW 2020+2024 / ZSQD） | **逐字节相同** |

## 七、子记录识别进度（用 8 组 BGL↔源 XML 配对交叉验证）

已解码：`0x19` 机场名、`0x1D` **滑行道名称表**、`0xCE` 跑道、`0x11` 跑道入口、`0x11A` COM、
`0x1A` 滑行道点、`0xD4` 滑行道路径、`0xE7` 机位、`0xD0` 停机坪、`0xCF` 画线、`0x31` 边灯、
`0xD9` **跑道标志牌 TaxiwaySign**、`0x57` **灯光支座 LightSupport**、
`0xDE` **登机桥 Jetway**（记录首 u16 = 机位号、航向 u16@+34×360/65536、容器名/缩放 @+88/+94；
用 ZSYA 源 XML 的 6 座桥逐字段验证：位置差 ≤0.02 m、航向差 ≤0.005°、型号与 scale 完全一致）、
`0x5A` **矢量放置 / 围栏**（u16 顶点数 + 16B profile GUID + scale + spacing + 双精度顶点；
北海 4 条折线合计 4.8 km，其中两条首尾相接 1.25 m，正合机场围栏尺度）、
`0xE8` **机场内嵌模型放置**（Ground / gpn / line 三个地面模型，GUID 由模型库反查；
scale 取 1.0 有依据：这三个 glTF 本身就是按真实米数建模，Ground 达 1032 × 3253 m）。

`0x5C` **Archetype 参数覆盖**（2024）：26 字节 = u16（恒 0）+ u64 参数名哈希 + f32 参数值 + 12 字节（多为 0，
个别是写入方没清的未初始化内存）。它**永远紧跟 `0x5D` AirportArchetype**（北海 1 条 archetype + 25 条覆盖；
虹桥 1 + 8 条；扫 71 个 Community BGL 共 44 条，前一条记录 3 次是 0x5D、40 次是同组的下一条 0x5C），
而 2024 官方 schema 的 `ctAirportArchetype` 只允许一种子元素 `<ParamOverride name value/>`，故确认为参数覆盖：
输出时展开成
  
```
<AirportArchetype archetypeGUID="{...}">
  <ParamOverride name="0xEB2BD1E88E1E1489" value="0.1"/>
</AirportArchetype>
```

参数名是哈希，原字符串无法反推（Community 与 SDK 里都没有带 `<ParamOverride>` 的源 XML 可对照），
因此 name 用大写 16 位十六进制；值越界（如 `1e38`）按未初始化内存处理、输出 0 并在摘要里计数。

语义已定、但 2020 profile 不输出：`0x5D` **AirportArchetype**、它的 `0x5C` 参数覆盖，以及画线的 `outlineType`
（均为 2024 专有，2020 的 bglcomp.xsd 里没有；2024 profile 照常输出）。

`0xFC` **航司代码表**（2024）：u16 条数 + 每条 4 字符代码（如福州长乐 = CXA、CJX）。该表在机位数组之前，
但机位记录里没有逐机位的引用字段，无法判断代码挂在哪些机位上，故只在界面/日志里报出，**不写进 XML**。
逐机位的航司代码另有出处：机位数组是变长条目，每条 56 字节主体后紧跟 `4 × N` 字节航司代码
（`N` 取条目首个 32 位整数的最高字节），这部分已按 `airlineCodes="AAA,BBB"` 输出（见 1.4.0）。

仍未知（结构已完全解出，但对应不到任何 XML 元素，故不输出）：
`0xD5`（武夷山 1 条 → 实为 208 条 48 字节块，GUID `{FBE4F3AE-D7D6-4EC8-8BC5-5A381C368173}` 全部相同，
块 = `GUID + u32 + 几个小整数 + f32 + 12 字节尾部`，语义未定，同样无对应元素）；
另有 CVX 显示方式字段待解（需 ExtractorLibrary.dll）。0xFB 已按 `<MastLight>` 输出（字段映射为推测）。
`0x118` 已解出结构并写入摘要/报告（见 1.3.4 新增），不再列入未解码。
本机 2024 版机场 schema 在 `C:\MSFS 2024 SDK\Tools\bin\bglcomp.xsd`（模拟器自带 `MSFS2024\bglComp.xsd` 同哈希），
2024/2020 两套输出都已用它做过 XSD 校验并 0 错误。
CVX 的 `encoding_method 1`（北海 2 处）需要官方 ExtractorLibrary.dll 才能还原，同样只记日志。

## 八、许可与出处

格式为本项目逆向所得，用于读取自有/已授权场景；请遵守相应插件的使用条款。
