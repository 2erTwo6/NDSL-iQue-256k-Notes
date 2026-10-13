# ndsl-hns-mod —— 去掉开机"健康与安全提示"的独立工作目录

这个目录是我（助手）为 DS Lite 固件魔改单独新建的，**不包含也不修改工作区里你项目的任何文件**。
原厂固件是从 `../从我的日版机DSL上提取的系统/FW001656B0043F/` **复制**过来的副本，只读使用。

> ### 本目录的 `tools/ndsl_mod.py` 现在是中文移植的关键依赖
>
> 上层那个 iQue 中文固件移植项目，用 `dsfwtool -comp` 重新压缩 P5 构建出的镜像
> 刷真机是**纯白屏**（背光亮、无 Logo），而同一份镜像在 melonDS 里完全正常。
> 把 `ndsl_mod.py` 的 `vpk_compress()` 拿来压**同一份解压数据**（60036 字节，
> 比 dsfwtool 的 61979 还小），真机就正常进中文界面了。
>
> 原因是 `dsfwtool` 的 vpk 编码器**只在任天堂原始流上 bit-exact**，对我们改过的
> 数据产出的流真机解压器不接受 —— 而 `dsfwtool -i`、三个 CRC、以及两个纯软件
> 解码器（melonDS 与 `ndsl_mod.py` 自己的）全都查不出问题，只有真机会暴露。
> 这正是本文件第 5 节第 2 条那类"格式规则"，只是长在了编码器上。
>
> 因此：**P3/P4/P5 要么原样透传任天堂的流，要么用 `ndsl_mod.py` 编码，
> 绝不要用 `dsfwtool -comp` 重新压缩。** 详见 `../README.md` 开头那一节。

```
factory/            原厂固件副本（只读）
  firmware.bin        md5 86f3adf73fe072593772cefb6f6426e9  ← 与你的原始 dump 一致
  biosnds7.rom        md5 df692a80a5b1bc90728bc3dfc76cd948  (KEY1 密钥表来自这里)
  biosnds9.rom
tools/ndsl_mod.py   自包含工具链：CRC16 / KEY1 / LZ77 / vpk / 解包 / 重打包 / 校验 / 补丁
out/                成品
  firmware_hns_autoskip.bin       ← 推荐：改动最小，保留原版淡入淡出与 1.5 秒停留
  firmware_hns_autoskip_240.bin   备选：停留改为 240 帧（≈4 秒）
```

---

## 1. 改了什么

**只有 2 个字节**（Part1 解压后 `0x0A0C`）：

```
原: 23 48   (ldr r0,[pc,#0x8c])   stage1 里"检测有没有按键/触摸"
新: 1A E0   (b 0xA44)             无条件跳到"放行"段
```

上下文（Part1 解压后，RAM 基址 `0x02320000`）：

```asm
0x096C  stage1 处理函数（开机警告画面的"等确认"阶段）
0x0A08  cmp  r0,#0x5a      ; 帧计数器 ≥90（≈1.5 秒）才往下走   ← 原版的最短停留
0x0A0A  ble  0x0A82        ; 不够 → 返回继续空转
0x0A0C  ldr  r0,[pc,#0x8c] ; ★ 被改掉：之后才是按键/触摸/60 秒超时检测
0x0A44  放行 → bl 0x18AC、计数器清零、stage=2（进入原版淡出）→ 菜单
```

**效果**：原版的淡入/淡出动画与 1.5 秒停留节奏**完整保留**，只是不再需要人点屏幕 ——
开机播放原版过场后自动进 DS 菜单。

---

## 2. 怎么用（以后自己再做一次 / 做别的改动）

```bash
cd ndsl-hns-mod

# 看结构 / 校验 / 解包
python3 tools/ndsl_mod.py info    factory/firmware.bin --bios factory/biosnds7.rom
python3 tools/ndsl_mod.py verify  factory/firmware.bin --bios factory/biosnds7.rom
python3 tools/ndsl_mod.py extract factory/firmware.bin --bios factory/biosnds7.rom -o out/extracted

# 打补丁：预设
python3 tools/ndsl_mod.py patch factory/firmware.bin --bios factory/biosnds7.rom \
        --preset hns-autoskip -o out/my.bin

# 打补丁：自定义（offset 用解压后偏移；old 字节用于防误伤，可留空）
python3 tools/ndsl_mod.py patch factory/firmware.bin --bios factory/biosnds7.rom \
        --spec 'part1:0x0A0C=2348>1ae0' -o out/my.bin
```

`patch` 会自动：校验原字节 → 改解压后镜像 → **重编码（Part1/2: LZ77+KEY1；Part3/4/5: vpk）**
→ 重算全部校验和 → 保存 → **回读再解压、逐项验证 5 个校验并打印改动范围**。

内置预设：

| preset | 效果 |
|---|---|
| `hns-autoskip` | **推荐**：保留 90 帧（≈1.5s）停留 + 原版动画，自动放行 |
| `hns-autoskip-240` | 同上，停留 240 帧（≈4s） |
| `hns-instant` | 只去掉 90 帧门槛（淡入一完就过，观感太快） |
| `hns-fade-instant` | 直接进 stage2 且淡出瞬时（可用但画面生硬） |

---

## 3. 验证证据（本次重建的自检结果）

| 检查 | 结果 |
|---|---|
| 原厂固件 5 项校验 | 全部复现：`0x06=0x0F1F`、`0x04=0xDB00`、`0x26=0x4F5D`、`0x2A=0xB3E6`、设置 `0x3889` → **KEY1 / LZ77 / vpk 三个解码器都 bit-exact** |
| 无改动重压 Part1 后再解包 | 输出 md5 = `86f3adf73fe072593772cefb6f6426e9`，**与原厂逐字节相同** → 编码器复刻原版成功 |
| 推荐成品 | md5 `fdf0b9802755d8af5e3c900931f5f143`，`0x06=0xCFC3`，5 项校验全过；**只改动了 18 个字节**（头部 2 字节 + 2 个 KEY1 块） |
| 240 帧版 | md5 `aa20e62e6474e7c14fdc37b5733ed634`，`0x06=0x5A8D`，5 项校验全过 |
| 差分范围 | Part2/3/4/5、WiFi 校准区、用户设置**逐字节未动** |

---

## 4. 在 melonDS 里验证

`Config → Emu settings → DS-mode`：关闭 HLE firmware，指定
`biosnds7.rom` / `biosnds9.rom` / `out/firmware_hns_autoskip.bin`，**不插卡**启动：

* 期望：原版开机过场（警告画面按原版淡入）→ 约 1.5 秒后**自动**淡出 → DS 菜单，
  全程不需要触摸或按键。
* 插卡启动：过场后直进游戏。

⚠️ melonDS 会把 DS 用户设置**写回它加载的那个 firmware.bin**（只动 `0x3FA00–0x3FFFF`）。
所以测试请用副本，`factory/firmware.bin` 与 `out/*.bin` 都留一份原始备份。

---

## 5. 未来魔改必读的几条规则

1. **改代码请改解压后镜像再重编码**，不要原地改压缩流：后面有匹配会回引到被改的位置（实测会污染多处）。
2. **LZ77 重叠匹配（长度 > 位移）必须偶位移**，否则真机/模拟器加载器解错 → 白屏。
   本工具已内置这条规则与"平局取最近匹配"，遵守时输出与原版一致。
3. **三个部件校验覆盖的是解压后数据**：`0x06`=Part1+2、`0x04`=Part3+4、`0x26`=Part5；
   改任何 part 都要重算（`patch` 已自动做）。`0x2A` 覆盖 WiFi 校准，用户设置校验在 `0x72`。
4. **`0x02A–0x1FF` 的 WiFi 校准区每机唯一（MAC/RF/BB），绝对不能覆盖**。
5. **槽位余量**：Part1 51232（原版流 51223）、Part2 34040（34039）、Part5 之后到 Part3 只剩几字节；
   Part4 之后到 AP 区约 1.6KB。若重编码后放不下，需搬移后续部件并改头部偏移（8/16 字节对齐）。
6. **`tools/ndsl_mod.py` 的 vpk 压缩器可用但比原版差约 6%**，改 Part3/4/5 内容时注意体积
   （优先"尺寸中性"改法，或搬移部件）。
7. 开机流程与关键地址（继续魔改时的入口）：
   ```
   F（显示初始化 + 警告画面装载）0x0DD8，装载调用 0x133C: bl 0x568C
   stage 跳转表 0x2F8，stage 变量 [0x023308E0+0x2C]
   菜单函数 0x027C（0x2944 淡出/撤销），状态机 0x7730（菜单/GUI 交接，别动）
   启动标志字 0x023549F0（映射函数 0x5840），flags 结构 0x02331AE0(+0x68)
   帧计数器 [0x023312E0+8]，输入块 0x02333D84（+0x20 触摸，+6 新按键），触摸状态 [0x02331B68]
   Part5 装载地址 0x023A4760（英语健康警告块 0x2A1C 起，WARNING 文本 0x2C68）
   ```
8. 真机刷写需要 fwmanage（并短接 SL1 写保护点）或硬件编程器；**没有备份与救砖手段不要刷**。
