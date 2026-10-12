# NDSL 256 KiB iQue 中文固件移植

把 512 KiB 神游 iQue DSL 固件中的中文 UI、字体和菜单资源移植到只有
256 KiB SPI Flash 的日版/外版 DS Lite 上，并在不移动 P5 资源起始地址的
前提下精简中文字库，使整个固件重新压缩后可以装进 256 KiB。

> 本仓库只包含脚本、文档和构建流程，**不包含任天堂/神游官方固件镜像、
> BIOS、最终固件或任何主机私有的 Wi-Fi 校准/MAC/用户设置数据**。
> 构建时必须由使用者提供合法 dump 和工具。

## 当前状态

- 已能构建出完整 256 KiB 固件镜像。
- 已通过 `dsfwtool -i` 校验分量布局和 CRC16。
- 已修正字体子集只统计旧 `JNLL` 消息、漏掉实际屏幕使用的 UTF-8 `DAT1`
  中文 UI 字符串的问题；被保留字形的位图和宽度数据与原神游字库逐字节一致。
- 已在 melonDS 中做启动烟测，可以正常进入中文 iQue 界面。
- 初版在 iQue Logo 后白屏的问题已定位并修复：512 KiB iQue 固件在 P1
  之前还有一段 `0x200..0x27F` 数据，`dsfwtool` 不会把它作为分量导出，
  重建时必须原样拷回，且 P1 起始地址需保持 `0x280`。
- **尚未在真实硬件上完成刷写验证**。刷 SPI Flash 有变砖风险，请先备份并准备好恢复方案。

## 仓库结构

```text
.
├── README.md
├── LICENSE
└── scripts
    ├── build_firmware.sh   # 一键构建 256 KiB 固件
    ├── make_header.py      # 生成 256 KiB iQue 主固件头
    ├── patch_pre_p1.py     # 补齐 dsfwtool 未建模的 P1 前数据区
    └── subset_p5.py        # 精简 JNCM/JNFR 字体资源
```

构建时产生的中间文件会放在 `build/`，最终镜像默认输出到 `dist/`。
仓库只跟踪脚本和文档；官方 dump、工具目录和构建产物默认不加入 Git，
如需版本化请自行 `git add`。

## 依赖

- Python 3
- [`dsfwtool`](https://github.com/Wokann/dsfwtool)：用于解密/解压、重压缩和
  重新组装 DS 固件。
- 可选：`armips`，仅在你需要自己改 P1/P3 汇编时使用。

`dsfwtool` 的 Linux 构建示例：

```bash
git clone https://github.com/Wokann/dsfwtool.git
cd dsfwtool
make
# 得到 release/dsfwtool，或者自己指定编译器
```

## 需要准备的文件

1. 神游 512 KiB 固件 dump，例如：

   ```text
   网友分享的神游DSL固件/idsl-fw.bin
   ```

2. 目标机器的 256 KiB 固件 dump，例如从日版 DSL 提取出的：

   ```text
   FW001656B0043F/firmware.bin
   ```

   目标 dump 用于保留该主机的 Wi-Fi 校准、MAC、Access Point 和用户设置。

不要提交、分发或公开包含主机私有数据的 dump 和最终镜像。

## 构建

假设 `dsfwtool` 已经在 `PATH` 中：

```bash
cd NDSL
export DSFWTOOL=/path/to/dsfwtool

# 默认路径可用时
./scripts/build_firmware.sh

# 或显式指定 dump
IQ_FW=/path/to/idsl-fw.bin \
TARGET_FW=/path/to/firmware.bin \
DSFWTOOL=/path/to/dsfwtool \
./scripts/build_firmware.sh
```

输出：

```text
dist/idsl-256k-chs.bin
```

## 实现原理

### 1. 固件头

神游 512 KiB 固件使用 `MACi` 标识、`console type 0x63`，用户设置位于
512 KiB 尾部。移植到 256 KiB 时需要：

- 保留 iQue `P1/P2` 的加密标识 `MACi`，保证 boot code 解密密钥一致。
- 把 flash 容量字段改为 256 KiB：

  ```text
  shift_amounts = 0x2CB2
  ```

- 把用户设置指针改为 256 KiB 位置：

  ```text
  user settings offset = 0x7FC0
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

实际精简结果：

| 字体 | 原字形数 | 保留字形数 | 说明 |
|---|---:|---:|---|
| JNFR #0 | 59 | 59 | 小字体，全部保留 |
| JNFR #1 | 26 | 26 | 小字体，全部保留 |
| JNFR #2 | 7226 | 688 | 主字体，中英文 `DAT1` 用字 + 完整键盘字符集 + 数字/`@` + `读` |
| JNFR #3 | 680 | 680 | 9x9 字体，完整保留，覆盖虚拟键盘全部字符 |

其中 `JNFR #2` 还显式补入了旧 `JNLL` 菜单字符串需要的 `U+8BFB 读`，避免最后
一个残留 `@`。P5 压缩后约 `61979` 字节；距离 256 KiB 固件的 P5/设置区边界
约 125 字节，余量极紧，不要再向 P5 增加字体/文本数据。

### 3. 分量布局

构建脚本使用固定物理偏移，以适配增大的 iQue `P1/P2`：

```text
P1 0x000280
P2 0x00F750
P3 0x017CB0
P4 0x0277C0
P5 0x030768
pre-P1 0x000200..0x00027F (从原 iQue dump 原样保留)
```

这里保持 iQue 原始物理偏移，而不是把 P1 下移到 `0x200`。原因是 512 KiB
iQue 固件在 P1 之前还有一段 `0x80` 字节的数据区，`dsfwtool` 的主头模型只
覆盖 `0x180` 字节头文件和 P1..P5 分量，不会导出这段数据；如果组装后不补回
它，开机时 iQue Logo 会一闪而过，随后上下屏保持白屏。

`dsfwtool` 会在组装时重新计算主头的分量起始地址、P1/P2/P3/P4/P5 CRC16
以及尾部用户设置指针。组装完成后，`scripts/build_firmware.sh` 会调用
`patch_pre_p1.py` 把源 iQue dump 的 `0x200..0x27F` 原样写回输出镜像。

## 校验

构建完成后可以检查布局：

```bash
dsfwtool -i dist/idsl-256k-chs.bin
```

字体静态校验思路：

- 重新解析 `JNCM`，确认映射长度与 `JNFR` 字形数一致。
- 遍历保留的中英文 `DAT1` 表，确认所有用字都在 `JNFR #2` 新映射中。
- 确认 `JNFR #2/#3` 都包含完整虚拟键盘字符集（大小写字母、西欧字符、假名、
  符号），避免键盘输入界面因字体子集出现 `@`。
- 对被保留的字形，对比新老 P5 中的宽度字节和位图字节是否一致。

## 刷写注意

本仓库输出的是**原始 256 KiB SPI Flash 固件镜像**，不是安装器。

- 刷写前必须完整备份原机 firmware/NVRAM。
- 推荐使用支持校验和恢复的 DS Lite NVRAM/固件刷写工具，例如 FlashMe/fwTool
  类工具或硬件编程器。
- 不要把本机 dump 构建出的镜像刷到另一台机器；不同主机的 Wi-Fi 校准、
  MAC 和触摸校准可能不同。
- 固件刷写有风险，操作者需要自行承担后果。

## 版权与隐私

- 本仓库不包含任天堂、神游或任何第三方的官方固件、BIOS、字体位图或最终镜像。
- 最终构建产物中包含使用者自己主机的 Wi-Fi 校准、MAC、Access Point 和用户设置，
  以及官方固件代码，默认不应公开分发。
- 脚本代码以 MIT 许可证发布；官方固件内容的权利归其各自权利人所有。

## 致谢

- [Wokann/dsfwtool](https://github.com/Wokann/dsfwtool)：DS 固件布局、
  P1/P2 加密、P3/P4/P5 压缩与重组工具。
- [Garhoogin/NitroPaint](https://github.com/Garhoogin/NitroPaint)：`NitroFont.c`
  中公开的 JNFR/JNCM/BNFR/BNCMP 读取与写入规则。
- [Wokann/dscfw](https://github.com/Wokann/dscfw)：DS 固件结构和 FlashMe
  逆向资料。
