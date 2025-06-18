# 心动匹配 - 后端服务

本项目是“心动匹配”应用的后端部分，提供了用户认证、数据管理、实时聊天和智能匹配等核心功能。

## 技术栈

- **Python 3**: 主要编程语言
- **Flask**: 轻量级Web框架，用于提供HTTP API接口
- **WebSockets**: 用于实现实时双向通信（聊天、匹配通知）
- **SQLite**: 轻量级数据库，用于存储用户信息、聊天记录等
- **Apscheduler**: 用于执行定时任务（例如机器人定时问候）
- **DeepSeek API**: 用于驱动机器人聊天功能

## 目录结构

```
.
├── backend/
│   ├── http_server.py       # Flask HTTP服务器，处理API请求
│   ├── websocket_server.py  # WebSocket服务器，处理实时消息
│   ├── config.py            # 统一的配置文件
│   ├── users.db             # SQLite数据库文件
│   └── ...
├── scripts/
│   └── ...                  # 各种数据处理和初始化脚本
├── requirements.txt         # Python依赖包列表
└── start_servers.py         # 主启动脚本
```

## 安装与启动

1.  **安装依赖**

    请确保你已安装 Python 3。然后通过 pip 安装所有必需的库：
    ```bash
    pip install -r requirements.txt
    ```

2.  **配置服务**

    所有关键配置项都位于 `backend/config.py` 文件中。你可以根据需要修改以下内容：
    - `DATABASE_PATH`: 数据库文件的路径
    - `HTTP_HOST` / `HTTP_PORT`: API服务的监听地址和端口
    - `WEBSOCKET_HOST` / `WEBSOCKET_PORT`: WebSocket服务的监听地址和端口
    - `DEEPSEEK_API_KEY`: DeepSeek AI的API密钥

3.  **启动服务**

    运行主启动脚本来同时启动HTTP和WebSocket服务器：
    ```bash
    python start_servers.py
    ```
    服务器成功启动后，你将看到API服务和WebSocket服务的地址。

## 功能概览

- **用户系统**: 注册、登录、个人资料管理。
- **匹配系统**:
    - 基于地理位置和性别的实时匹配。
    - 超时后自动匹配AI机器人。
- **聊天系统**:
    - 支持一对一私聊。
    - 支持与AI机器人聊天。
    - 实时打字状态提示。
- **机器人系统**:
    - AI机器人可以模拟真实用户进行对话。
    - 定时任务，让机器人主动向真实用户发送问候。
