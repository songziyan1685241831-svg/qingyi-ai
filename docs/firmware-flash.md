# 固件烧录教程

> 将修改后的 ESP32 固件烧录到开发板

---

## 前置准备

- ESP32-S3 开发板（已到手）
- Type-C 数据线
- 电脑（Windows/Mac/Linux均可）
- 修改后的固件文件（从 GitHub Releases 下载）

## 1. 下载烧录工具

推荐使用 **ESP32 Flash Download Tool**（乐鑫官方工具）：

```
下载地址：https://www.espressif.com/en/support/download/other-tools
选择：Flash Download Tools
```

## 2. 连接开发板

```text
① 用 Type-C 线连接开发板和电脑
② 电脑应出现新串口设备
   - Windows: 设备管理器中查看 COM 口
   - Mac: ls /dev/cu.*
   - Linux: ls /dev/ttyUSB* 或 /dev/ttyACM*
```

## 3. 固件修改说明

本项目基于 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 开源项目，需要修改服务器地址：

**文件位置：** `main/protocols/websocket_protocol.cc`

```cpp
// 修改前（连官方服务器）
std::string url = settings.GetString("url");

// 修改后（连你的服务器）
// 在你的 server.py 配置中设置 WebSocket URL
```

## 4. 烧录步骤

1. 打开 Flash Download Tool
2. 选择芯片类型：**ESP32-S3**
3. 选择烧录方式：**UART**
4. 配置烧录参数：

| 参数 | 值 |
|------|-----|
| 波特率 | 921600 |
| Flash 大小 | 16MB（依开发板而定） |
| Flash 模式 | QIO |

5. 添加固件文件：

| 文件 | 地址 |
|------|------|
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| ota_data_initial.bin | 0x6000 |
| xiaozhi.bin | 0x10000 |

6. 选择正确的 **COM 端口**
7. 点击 **START** 开始烧录
8. 等待进度条完成

## 5. 首次启动

1. 断开 USB，重新上电
2. 设备进入配网模式，屏幕显示二维码
3. 用手机微信扫码，输入 Wi-Fi 密码
4. 设备自动连接你的服务器

## 6. 验证连接

查看服务器日志：

```bash
tail -f /opt/ai-bot/bot.log
```

应看到类似输出：

```
INFO:Bot:设备上线: abc12345
```

## 7. 开始对话

唤醒设备（默认唤醒词：你好琴一），然后说话，你的机器人会通过你的服务器进行对话。
