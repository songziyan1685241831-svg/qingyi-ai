# 服务端部署指南

> 从零开始，在云服务器上搭建琴一AI服务端

---

## 前置准备

- 一台云服务器（推荐腾讯云轻量，2核2G，Ubuntu 22.04，¥34/月）
- 已注册的火山引擎语音服务账号
- 已注册的 DeepSeek API 账号

## 1. 登录服务器

```bash
ssh ubuntu@你的服务器IP
```

## 2. 安装依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip
pip3 install fastapi uvicorn websockets httpx edge-tts pycryptodome
```

## 3. 上传代码

在本地电脑（你的 Windows）上：

```bash
scp server/server.py ubuntu@你的服务器IP:/opt/ai-bot/server.py
```

## 4. 配置密钥

编辑 `server/server.py`，找到顶部配置区：

```python
VOLC_APPID = "你的火山引擎AppID"        # 从 https://console.volcengine.com/speech/app 获取
VOLC_AT = "你的火山引擎AccessToken"     # 同上
DS_KEY = "你的DeepSeek API Key"         # 从 https://platform.deepseek.com/api_keys 获取
```

## 5. 启动服务

```bash
cd /opt/ai-bot
nohup python3 server.py > bot.log 2>&1 &
```

## 6. 验证运行

```bash
curl http://localhost:8000
# 应返回: {"status":"ok","name":"AI-Bot",...}
```

## 7. 开放防火墙

需要在**两个地方**开放端口 8000 和 8001：

### 7.1 服务器内部防火墙（UFW）

```bash
sudo ufw allow 8000/tcp
sudo ufw allow 8001/tcp
```

### 7.2 云厂商安全组

登录云厂商控制台，找到服务器安全组/防火墙，添加规则：

| 协议 | 端口 | 来源 | 说明 |
|------|------|------|------|
| TCP | 8000 | 0.0.0.0/0 | HTTP 配置页面 |
| TCP | 8001 | 0.0.0.0/0 | WebSocket 设备连接 |

## 8. 访问配置页面

打开浏览器访问：

```
http://你的服务器IP:8000/config
```

现在你可以配置机器人的名字、性格、音色了。
