# 琴一 AI · Qinyi AI 🤖

> 你的专属桌面 AI 陪伴机器人 — 从零开始的完整开源方案

---

## 📌 项目简介

基于 **ESP32 硬件** + **自建云服务器** + **大语言模型**，打造一台完全属于你自己的 AI 陪伴机器人。

它不是成品，而是**一套你可以自己搭建、自己掌控、自己扩展的开源方案**。

### 核心特性

| 特性 | 说明 |
|------|------|
| 🎙️ 语音交互 | 唤醒 → 说话 → 识别 → 大模型回复 → 语音合成 |
| 🧠 大模型驱动 | 接入 DeepSeek 等大模型，你说什么它都懂 |
| 🎤 语音识别 | 火山引擎 ASR，实时转文字 |
| 🔊 语音合成 | 多种免费音色可选（女声、男声、方言等） |
| 🌐 网页配置 | 随时在线修改角色性格、音色、语速 |
| 🔓 完全自主 | 服务器、固件、数据全归你管 |
| 📈 成本可控 | 硬件 ~85 元 + 服务器 ¥34/月 |

---

## 🏗️ 系统架构

```
┌─────────────────────┐
│   ESP32 硬件         │
│   (开发板 + 屏+麦+喇叭) │
└─────────┬───────────┘
          │ WebSocket (Opus 音频)
          ▼
┌─────────────────────┐
│   腾讯云轻量服务器      │  ← ¥34/月
│                      │
│  ┌─────────────────┐ │
│  │  Python 服务端    │ │
│  │                  │ │
│  │  · WebSocket 网关 │ │  ← :8001 连 ESP32
│  │  · ASR 语音识别   │ │  ← 火山引擎
│  │  · LLM 大模型     │ │  ← DeepSeek API
│  │  · TTS 语音合成   │ │  ← Edge TTS
│  │  · 网页配置页     │ │  ← :8000/config
│  └─────────────────┘ │
└───────────────────────┘
```

### 一次对话的完整流程

```
你说话 → ESP32 录音 → Opus 编码 → WebSocket 发送
         → 服务端接收 → 火山引擎 ASR(语音转文字)
         → DeepSeek LLM(理解+生成回复)
         → Edge TTS(文字转语音)
         → WebSocket 回传 → ESP32 播放 → 你听到回答
```

---

## 📦 硬件清单

### 最低成本方案（~85 元，全部免焊）

| 物品 | 说明 | 参考价 |
|------|------|--------|
| **ESP32-S3 开发板** | 带屏幕、麦克风、喇叭接口，卖家已焊好 | ~70 元 |
| **18650 锂电池** | 带插头版本，不需焊接 | ~15 元 |
| **Type-C 数据线** | 烧录固件用，手头有则免 | - |
| **合计** | | **~85 元** |

> 也可直接购买 **ESP32-S3-BOX3**（~150 元），彩屏触摸、内置电池，到手即用。

### 购买建议

淘宝搜索关键词：`ESP32-S3 小智 AI 开发板`

下单前请确认卖家：
- ✅ 带显示屏
- ✅ 带麦克风
- ✅ 有喇叭接口（或自带喇叭）

---

## 🚀 快速开始

### 1. 部署服务端

```bash
# 购买一台云服务器（推荐腾讯云轻量，2核2G，Ubuntu 22.04）
# SSH 登录后执行：

# 安装依赖
sudo apt update && sudo apt install -y python3 python3-pip
pip3 install fastapi uvicorn websockets httpx edge-tts pycryptodome

# 上传 server.py 到服务器
# 启动服务
cd /opt/ai-bot && nohup python3 server.py > bot.log 2>&1 &

# 验证
curl http://localhost:8000
# 应返回 {"status":"ok","name":"AI-Bot",...}
```

### 2. 配置密钥

打开配置文件 `server.py`，在顶部找到配置区域：

```python
# ====== 请在这里填入你的密钥 ======
VOLC_APPID = "你的火山引擎AppID"
VOLC_AT = "你的火山引擎AccessToken"
DS_KEY = "你的DeepSeek API Key"
```

你需要注册以下服务：
- **火山引擎语音**：https://console.volcengine.com/speech/app（免费额度）
- **DeepSeek**：https://platform.deepseek.com/api_keys（价格极低）

### 3. 烧录固件

硬件到手后，按以下步骤操作：

```
① 下载 ESP32 Flash Download Tool
② 获取修改后的 xiaozhi-esp32 固件（服务器地址改为你的 IP）
③ USB 连接开发板与电脑
④ 选择固件 → 点击烧录
⑤ 上电 → 配网 → 开始对话
```

> 固件修改说明：将 `websocket_protocol.cc` 中的服务器地址改为 `ws://你的服务器IP:8001`

### 4. 配置机器人

浏览器打开配置页面：

```
http://你的服务器IP:8000/config
```

可修改：
- 机器人名字
- 性格提示词
- TTS 音色（10+ 种选择）
- 语速

---

## 📁 项目结构

```
qinyi-ai/
├── server/
│   ├── server.py              # 服务端主程序
│   └── requirements.txt       # Python 依赖
├── firmware/
│   └── (待补充)               # ESP32 固件配置
├── docs/
│   ├── deployment.md          # 服务端部署指南
│   ├── firmware-flash.md      # 固件烧录教程
│   └── hardware-guide.md      # 硬件采购与组装
└── README.md                  # 本文件
```

---

## 📊 月度运营成本

| 项目 | 费用 | 说明 |
|------|------|------|
| 云服务器 | ¥34 | 腾讯云轻量 2核2G |
| DeepSeek API | ¥2-5 | 日常使用 |
| 火山引擎 ASR | 免费 | 免费额度 |
| Edge TTS | 免费 | 微软免费服务 |
| **月合计** | **~¥40** | |

---

## 🔧 扩展方向

- [ ] **摄像头视觉**：ESP32 接摄像头，拍照分析画面
- [ ] **声音克隆**：用火山引擎复刻你的声音
- [ ] **舵机动作**：让机器人会动
- [ ] **智能家居**：通过 MCP 协议控制设备
- [ ] **手机 APP**：已有开源 Android 客户端可适配
- [ ] **自定义唤醒词**：训练你专属的唤醒词

---

## 📜 开发历程

本项目记录了从零开始的完整开发过程：

1. **第 1 天** — 了解 xiaozhi-esp32 开源项目，评估方案
2. **第 2 天** — 确定自定义服务端方案，购买云服务器
3. **第 3 天** — 部署服务端，配置页面上线，打通全链路
4. **第 4 天** — 确定硬件方案，完善配置页面
5. **进行中** — 采购硬件，烧录固件，整机联调

---

## 🙏 致谢

- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 开源 ESP32 固件方案（MIT 协议）
- [火山引擎](https://www.volcengine.com/) — 语音识别服务
- [DeepSeek](https://platform.deepseek.com/) — 大语言模型
- [Edge TTS](https://github.com/rany2/edge-tts) — 免费语音合成

---

## 📄 许可证

MIT License

```
Copyright (c) 2026 songziyan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software...
```
# qingyi-ai
作者利用单片机创造 AI 陪伴机器人的整个过程
