# NDSL 256 KiB iQue 中文固件移植

把 512 KiB 神游 iQue DSL 固件中的中文 UI、字体和菜单资源移植到只有
256 KiB SPI Flash 的日版/外版 DS Lite 上，并在不移动 P5 资源起始地址的
前提下精简中文字库，使整个固件重新压缩后可以装进 256 KiB。

> **已在真实日版 DS Lite 上刷写验证通过，可以正常进入中文 iQue 界面。**
> 构建请用 `scripts/build_firmware_userp5.sh`，不要用 `scripts/build_firmware.sh`
> （后者在模拟器里正常、刷真机白屏，见下面第 7 条）。

> 本仓库只包含脚本、文档和构建流程，**不跟踪任天堂/神游官方固件镜像、
> BIOS、最终固件或任何主机私有的 Wi-Fi 校准/MAC/用户设置数据**。
> 构建时必须由使用者提供合法 dump 和工具。

---

## 最关键的一条：P3/P4/P5 的压缩流不能用 `dsfwtool` 重新压缩

**现象**：用 `dsfwtool -comp` 重新压缩 P5 构建出的镜像，`dsfwtool -i` 校验全过、
三个 CRC 全对、在 melonDS 里能正常进中文界面，**但刷进真机是"背光亮着、
连 Logo 都没有"的纯白屏**。

**原因**：`dsfwtool` 的 vpk(P345) 编码器**能正确解码**任天堂的原始流，而且在
**原始** P3/P4 数据上重压还能做到**逐字节相同**，但它对我们改过的 P5 数据压出来的
流，**真机的解压器不接受**。模拟器与两个纯软件解码器都更宽松，所以查不出来。

**规则**：

- P3/P4/P5 **要么原样透传任天堂的原始流**（本项目里 P3/P4 就是这么做的），
- **要么用 `ndsl-hns-mod/tools/ndsl_mod.py` 的 `vpk_compress()` 编码**，
- **绝不要用 `dsfwtool -comp` 重新压缩。**

同一份解压后的 P5，两种编码器的结果：

| 编码器 | 压缩后 | 真机 |
|---|---:|---|
| `dsfwtool -comp` | 61979 字节 | ❌ 白屏 |
| `ndsl_mod.py` `vpk_compress()` | **60036 字节** | ✅ 正常启动 |

---

## 当前状态

- ✅ **已在真实日版 DS Lite 上刷写验证通过**，正常进入中文 iQue 界面。
- ✅ 已通过 `dsfwtool -i` 校验分量布局和 CRC16；三个分量 CRC 与头部 Wi-Fi
  配置 CRC 均复算吻合。
- ✅ 已修正字体子集只统计旧 `JNLL` 消息、漏掉实际屏幕使用的 UTF-8 `DAT1`
  中文 UI 字符串的问题；被保留字形的位图和宽度数据与原神游字库逐字节一致。
- ✅ 已在 melonDS 中做启动烟测（注意：**模拟器通过不等于真机通过**，见上）。
- ✅ 初版在 iQue Logo 后白屏的问题已定位并修复：512 KiB iQue 固件在 P1
  之前还有一段 `0x200..0x27F` 数据，`dsfwtool` 不会把它作为分量导出，
  重建时必须原样拷回，且 P1 起始地址需保持 `0x280`。
- ⚠️ 刷 SPI Flash 有变砖风险，请先备份并准备好恢复方案。

构建产物：`dist/idsl-256k-chs-userp5.bin`

```text
sha256  29d863dec6b5e06d4acf9d6ce9908a61cd1a52a05a40ebccf2a806a243c46d8f
```

（`dist/not-working-do-not-flash/` 下放的是过程中产生的、**已知刷真机白屏或黑屏**
的旧镜像，仅供排查参考，不要刷。）

---

## 踩坑记录

1. **按错了文本源**
   一开始只解析 P5 里的 `JNLL` UTF-16LE 消息，但系统 UI 实际显示的是
   UTF-8 `DAT1` 表；结果 `想`、`幕`、`上方的液晶屏` 等字被删掉，回退成 `@`。

2. **清空 JNLL 导致启动白屏**
   为了腾空间曾把旧 `JNLL` 块整体清零，结果开机白屏。说明 `JNLL` 区域
   仍会被启动或早期 UI 路径访问，必须原样保留。

3. **虚拟键盘不是只用一个字体**
   只修改 `JNFR #3` 时键盘 `@` 完全没变化，说明键盘还会使用 `JNFR #2`。
   最终把完整键盘字符集同时加入 `JNFR #2`，并完整保留 `JNFR #3`，键盘
   才完全正常。

4. **清掉英文表影响系统其他界面**
   为省空间清空英文 `DAT1` 后，部分系统界面显示异常。最终恢复中文和英文
   表，只清法/德/意/西四张表。

5. **最后一个 “读” 不在 DAT1 中**
   `U+8BFB 读` 只出现在残留 `JNLL` 字符串里，且原 9x9 字体本身不含该
   字形；最后单独加入 `JNFR #2`。

6. **P5 余量**
   用 `dsfwtool` 编码时 P5 压缩后 `61979` 字节，距边界只剩 `125` 字节，
   所以不要随意再向 P5 增加字体或文本数据。改用 `ndsl_mod.py` 编码后是
   `60036` 字节，余量约 `2068` 字节，宽松不少。

7. **实机白屏的真凶：P5 用的压缩流编码器**（详见文首那一节）
   `dsfwtool` 的编码器在任天堂原始数据上 bit-exact，但在我们改过的 P5 上
   产出的流真机不接受。`dsfwtool -i`、三个 CRC、两种软件解码器全部通过，
   **静态检查查不出这个问题** —— 只有真机会暴露。改用
   `ndsl_mod.py` 的 `vpk_compress()` 压同一份解压数据即解决。

8. **排查白屏时走过的弯路（记录以免重走）**
   - 换用目标机自己的 ARM7 引导代码（P2）→ 现象无任何变化，
     说明 P2 的芯片相关处理不是原因；
   - 给 iQue 的 P1 打上"跳过开机健康提示"补丁（`0x0A48: 2348 → 1ae0`）→
     现象无变化，说明开机早期警告画面那条路不是原因；
   - 反过来用目标机固件当底座、只把 P3/P5 换成 iQue 的 → 变成**黑屏**
     （屏幕完全不点亮）。原因是**部件不能跨固件版本互换**：iQue 的 P5 解压后
     `387744` 字节，而目标机 P1 是按 `239520` 字节装载的（RAM 基址
     `0x023A4760`），会冲出主 RAM 末尾 `12288` 字节。
   - 想"只清位图、保留 JNCM/JNFR 结构原样"的子集方案（`subset_p5_min.py`）也
     试过：**塞不下**。P5 槽位压缩后上限 `62104` 字节，保留全部结构时压出来
     `75097` 字节（即使清掉法德意西四张文本表）。省下来的空间恰恰来自
     `JNCM` 码点表和字体宽度表本身，而这两张表删不得（P1 早期要读）。

---

## 仓库结构

**版本库里只有脚本、文档和 `ndsl_mod.py` 编码器**，不含任何固件 dump、构建产物
或镜像（它们要么是官方固件，要么含主机私有的 Wi-Fi 校准/MAC）。下面用
`[入库]` / `[本地]` 标出每个条目的状态。

```text
.
├── README.md                     [入库]
├── LICENSE                       [入库]
├── .gitignore                    [入库]
├── scripts                       [入库]
│   ├── build_firmware_userp5.sh  # ★ 正式构建：P5 用 ndsl_mod.py 编码
│   ├── build_firmware.sh         # 早期版本，真机白屏，仅作参考
│   ├── make_header.py            # 生成 256 KiB iQue 主固件头
│   ├── patch_pre_p1.py           # 补齐 dsfwtool 未建模的 P1 前数据区
│   ├── subset_p5.py              # 精简 JNCM/JNFR 字体资源
│   ├── subset_p5_min.py          # 另一路子集：只清位图、结构不动（放不下，留档）
│   └── build_variant_jp_p2.sh    # 反向/变体构建脚本（排查用，见第 8 条）
├── ndsl-hns-mod                  # 独立的固件魔改工具链
│   └── tools/ndsl_mod.py         # [入库] ★ vpk/LZ77 编码器 + KEY1 + 校验（本移植依赖它）
├── build/                        # [本地] 构建中间文件，由脚本生成
├── dist/                         # [本地] 最终镜像，由脚本生成
│   └── not-working-do-not-flash/ # [本地] 已知白屏/黑屏的旧镜像
├── 网友分享的神游DSL固件/          # [本地] 使用者自备：神游 512 KiB 固件 dump
│   └── idsl-fw.bin
└── 从我的日版机DSL上提取的系统/    # [本地] 使用者自备：目标机 256 KiB 固件 dump
    └── FW001656B0043F/firmware.bin
```

`ndsl-hns-mod/factory/`（原厂固件副本）和 `ndsl-hns-mod/out/`（去掉开机健康提示
的固件）同样属于 `[本地]`，含官方固件内容，默认不入版本库。

构建时产生的中间文件放在 `build/`，最终镜像输出到 `dist/`。**刚 clone 下来的
仓库里没有 `build/`、`dist/` 和两份 dump**，需要按下面的"需要准备的文件"自备，
再运行构建脚本生成。

---

## 依赖

- Python 3
- [`dsfwtool`](https://github.com/Wokann/dsfwtool)：DS 固件的解密/解压、
  重新组装与校验。**注意其 P345 编码器不能用于重新压缩 P5**（见文首）。
- `ndsl-hns-mod/tools/ndsl_mod.py`（仓库内）：P3/P4/P5 的 vpk 编码器，
  以及 P1/P2 的 LZ77 + KEY1 编解码。**本移植的 P5 必须用它编码。**
- 可选：`armips`，仅在你需要自己改 P1/P3 汇编时使用。

`dsfwtool` 的 Linux 构建示例：

```bash
git clone https://github.com/Wokann/dsfwtool.git
cd dsfwtool
make
# 得到 release/dsfwtool，或者自己指定编译器
```

---

## 需要准备的文件

1. 神游 512 KiB 固件 dump，例如：

   ```text
   网友分享的神游DSL固件/idsl-fw.bin
   ```

2. 目标机器的 256 KiB 固件 dump，例如从日版 DSL 提取出的：

   ```text
   从我的日版机DSL上提取的系统/FW001656B0043F/firmware.bin
   ```

   目标 dump 用于保留该主机的 Wi-Fi 校准、MAC、Access Point 和用户设置。

不要提交、分发或公开包含主机私有数据的 dump 和最终镜像。

---

## 构建

```bash
cd NDSL
export DSFWTOOL=/path/to/dsfwtool

# 默认路径可用时
./scripts/build_firmware_userp5.sh

# 或显式指定路径
IQ_FW=/path/to/idsl-fw.bin \
TARGET_FW=/path/to/firmware.bin \
DSFWTOOL=/path/to/dsfwtool \
MODTOOL=/path/to/ndsl-hns-mod/tools/ndsl_mod.py \
./scripts/build_firmware_userp5.sh
```

输出：

```text
dist/idsl-256k-chs-userp5.bin
```

脚本最后会自动跑 `dsfwtool -i` 打印分量布局，并输出 `sha256sum`。

---

## 实现原理

### 1. 固件头

神游 512 KiB 固件使用 `MACi` 标识、`console type 0x63`，用户设置位于
512 KiB 尾部。移植到 256 KiB 时需要：

- 保留 iQue `P1/P2` 的加密标识 `MACi`，保证 boot code 解密密钥一致。
- 把 flash 容量字段改为 256 KiB：

  ```text
  shift_amounts = 0x2CB2      # bit12-15 = 容量/128K = 2
  ```

- 把用户设置指针改为 256 KiB 位置：

  ```text
  user settings offset = 0x7FC0   # → 0x3FE00
  ```

- 从目标机 dump 复制 `0x2A..0x17F` 的 Wi-Fi 校准和 MAC 数据，避免无线校准丢失。
- 用目标机 dump 的尾部数据更新 Access Point 和用户设置区。

`scripts/make_header.py` 负责这些修改。

### 2. P5 字体格式

神游固件 P5 中含四组字体资源：

- `JNCM`：BNCMP 1.2 字符映射表，负责 Unicode 码点到字形索引的映射。
- `JNFR`：BNFR 1.2 位图字体，包含字形宽度表和 1bpp 位图。

中文字库由 `JNFR #2` 提供，原始共 `7226` 个字形。直接保留时 P5 压缩后
约 `170 KiB`，无法放进 256 KiB 固件。`scripts/subset_p5.py` 的做法是：

1. 解析 P5 中的 UTF-8 `DAT1` 文本表；系统 UI 实际显示的是这些字符串，
   旧 `JNLL` UTF-16LE 消息只是同内容的遗留副本。
2. `JNFR #2` 保留中文和英文 `DAT1` 表的用字，并额外加入完整的虚拟键盘
   字符集（大小写字母、西欧字符、假名、符号），以及运行时数字和 `@`。
3. `JNFR #3`（9x9 小字体）完整保留原字体全部 `680` 个字形；它同时是虚拟
   键盘字体，包含大量 `DAT1` UI 字符串没有引用到的键盘字符。
4. 原地清空法、德、意、西四张非中文、非英文 `DAT1` 文本表的数据区，
   保留表头/长度字段；中文和英文表保留，旧 `JNLL` 块完全保留不动。
5. 只复制被保留字形的宽度数据和位图记录。
6. 按 NitroPaint/BNCMP 1.2 的规则重写 `JNCM` 字符映射。
7. 原地写回原 `JNCM/JNFR` 起始地址，未使用区域填 `0x00`，不移动其他 P5 资源。
8. **压缩这一步必须用 `ndsl_mod.py`**，不能用 `dsfwtool -comp`（见文首）。

实际精简结果：

| 字体 | 原字形数 | 保留字形数 | 说明 |
|---|---:|---:|---|
| JNFR #0 | 59 | 59 | 小字体，全部保留 |
| JNFR #1 | 26 | 26 | 小字体，全部保留 |
| JNFR #2 | 7226 | 688 | 主字体，中英文 `DAT1` 用字 + 完整键盘字符集 + 数字/`@` + `读` |
| JNFR #3 | 680 | 680 | 9x9 字体，完整保留，覆盖虚拟键盘全部字符 |

其中 `JNFR #2` 还显式补入了旧 `JNLL` 菜单字符串需要的 `U+8BFB 读`，避免最后
一个残留 `@`。

`JNFR #2` 的码点列表（含 `P5+0x2A1C`、`P5+0x2C68` 两处）会被第 6 步重写 ——
**这是不可避免的**：保留结构原样的方案塞不进 256 KiB（见第 8 条），而 P1 在
开机早期会读这些表。实测这份重写过的表在真机上是可用的，出问题的只是压缩流
的编码器。

### 3. 分量布局

构建脚本使用固定物理偏移，以适配增大的 iQue `P1/P2`：

```text
P1       0x000280
P2       0x00F750
P3       0x017CB0
P4       0x0277C0
P5       0x030768
pre-P1   0x000200..0x00027F (从原 iQue dump 原样保留)
AP 区    0x03FA00
用户设置 0x03FE00 / 0x03FF00
```

这里保持 iQue 原始物理偏移，而不是把 P1 下移到 `0x200`。原因是 512 KiB
iQue 固件在 P1 之前还有一段 `0x80` 字节的数据区，`dsfwtool` 的主头模型只
覆盖 `0x180` 字节头文件和 P1..P5 分量，不会导出这段数据；如果组装后不补回
它，开机时 iQue Logo 会一闪而过，随后上下屏保持白屏。

`dsfwtool` 会在组装时重新计算主头的分量起始地址、P1/P2/P3/P4/P5 CRC16
以及尾部用户设置指针。组装完成后，`scripts/build_firmware_userp5.sh` 会调用
`patch_pre_p1.py` 把源 iQue dump 的 `0x200..0x27F` 原样写回输出镜像。

---

## 校验

### 构建后检查布局与 CRC

```bash
dsfwtool -i dist/idsl-256k-chs-userp5.bin
```

期望：

```text
identifier: 'MACi'    console type: 0x63    shift amounts: 0x2CB2
user settings offset: 0x7FC0
CRC16: P1/P2=0x87C4  P3/P4=0x0ED0  P5=0x0EB9
Wi-Fi config CRC: 0xB3E6  length=0x0138 (valid)
P1 0x000280 / P2 0x00F750 / P3 0x017CB0 / P4 0x0277C0 / P5 0x030768
P5 effective = 0x00EA84 (60036 字节)
```

三个 CRC 覆盖的都是**解压后**的数据：

- `0x06` = crc16(解压 P1 ++ 解压 P2, init 0xFFFF)
- `0x04` = crc16(解压 P3 ++ 解压 P4, init 0xFFFF)
- `0x26` = crc16(解压 P5, init 0xFFFF)
- `0x2A` = crc16(fw[0x2C : 0x2C+len], init 0x0000)
- 用户设置每个 `0x100` 扇区：`0x72` = crc16(block[0:0x70], init 0xFFFF)；
  若 `block[0x74] == 1` 还需 `0xFE` = crc16(block[0x74:0xFE], init 0xFFFF)

### 字体静态校验思路

- 重新解析 `JNCM`，确认映射长度与 `JNFR` 字形数一致。
- 遍历保留的中英文 `DAT1` 表，确认所有用字都在 `JNFR #2` 新映射中。
- 确认 `JNFR #2/#3` 都包含完整虚拟键盘字符集（大小写字母、西欧字符、假名、
  符号），避免键盘输入界面因字体子集出现 `@`。
- 对被保留的字形，对比新老 P5 中的宽度字节和位图字节是否一致。

### 压缩流校验（重要）

`ndsl_mod.py` 的 `vpk_compress()` 压完要立刻用 `vpk_decompress()` 解回来比对：

```python
import ndsl_mod as nm
data = nm.vpk_compress(open("build/ique_p5_subset.bin", "rb").read())
assert nm.vpk_decompress(data) == open("build/ique_p5_subset.bin", "rb").read()
```

**但请注意：这一步过了也不代表真机能用。** `dsfwtool` 压出来的流同样能通过
这一步和各种 CRC 校验，真机却是白屏 —— 见文首。**能查的静态检查都过了之后，
唯一的验证手段还是刷进真机。**

---

## 刷写注意

本仓库输出的是**原始 256 KiB SPI Flash 固件镜像**，不是安装器。

- 刷写前必须完整备份原机 firmware/NVRAM。
- 推荐使用支持校验和恢复的 DS Lite NVRAM/固件刷写工具，例如 FlashMe/fwTool
  类工具或硬件编程器。
- 不要把本机 dump 构建出的镜像刷到另一台机器；不同主机的 Wi-Fi 校准、
  MAC 和触摸校准可能不同。
- 换过网卡/Wi-Fi 板之后第一次开机，触摸屏可能需要重新校准。
- 固件刷写有风险，操作者需要自行承担后果。

---

## 版权与隐私

- 脚本代码以 MIT 许可证发布；官方固件内容的权利归其各自权利人所有。
- 最终构建产物中包含使用者自己主机的 Wi-Fi 校准、MAC、Access Point 和用户设置，
  以及官方固件代码，默认不应公开分发。
- **提交前注意**：本仓库当前只跟踪脚本、文档和 `ndsl_mod.py`；官方固件 dump、
  构建中间产物和成品镜像（`extract/`、`work/`、`build/`、`dist/`、两份 dump 目录、
  根目录的 `idsl-256k-chs.bin` 等）已由 `.gitignore` 排除。
  如果你在本机重新生成了这些内容，**不要让它们进入提交**：成品镜像里含你自己
  主机的 Wi-Fi 校准、MAC 和用户设置。可用 `git status` 确认它们没有被跟踪。
- 正式产物是 `dist/idsl-256k-chs-userp5.bin`（`[本地]`，不入库，含主机私有数据）。
  根目录若出现 `idsl-256k-chs.bin`，那是早期 **白屏版本**，不是正式产物。

---

## 致谢

- [Wokann/dsfwtool](https://github.com/Wokann/dsfwtool)：DS 固件布局、
  P1/P2 加密、P3/P4/P5 解压与重组工具。
- `ndsl-hns-mod/tools/ndsl_mod.py`（本仓库内）：P3/P4/P5 的 vpk 编码器，
  以及 P1/P2 的 LZ77 + KEY1 编解码。本移植能上真机靠的就是它的
  `vpk_compress()`。
- [Garhoogin/NitroPaint](https://github.com/Garhoogin/NitroPaint)：其源码中的
  `NitroFont.c` 公开了 JNFR/JNCM/BNFR/BNCMP 的读取与写入规则。
  （该文件属于上游项目，不在本仓库内；本仓库的 `subset_p5.py` 依据它的规则实现。）
- [Wokann/dscfw](https://github.com/Wokann/dscfw)：DS 固件结构和 FlashMe
  逆向资料。
