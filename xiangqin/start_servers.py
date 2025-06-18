#!/usr/bin/env python3
"""
心动匹配应用启动脚本
同时启动HTTP服务器和WebSocket服务器
"""

import subprocess
import sys
import time
import signal
import os
from threading import Thread
from backend import config

class ServerManager:
    def __init__(self):
        self.http_process = None
        self.websocket_process = None
        self.running = True
    
    def start_http_server(self):
        """启动HTTP服务器"""
        print(f"🚀 启动HTTP服务器 (端口 {config.HTTP_PORT})...")
        try:
            self.http_process = subprocess.Popen(
                [sys.executable, "backend/http_server.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,  # universal_newlines is an alias for text
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )
            
            # 输出HTTP服务器日志
            for line in iter(self.http_process.stdout.readline, ''):
                if self.running:
                    print(f"[HTTP] {line.strip()}")
                else:
                    break
                    
        except Exception as e:
            print(f"❌ HTTP服务器启动失败: {e}")
    
    def start_websocket_server(self):
        """启动WebSocket服务器"""
        print(f"🔗 启动WebSocket服务器 (端口 {config.WEBSOCKET_PORT})...")
        try:
            self.websocket_process = subprocess.Popen(
                [sys.executable, "backend/websocket_server.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,  # universal_newlines is an alias for text
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )
            
            # 输出WebSocket服务器日志
            for line in iter(self.websocket_process.stdout.readline, ''):
                if self.running:
                    print(f"[WebSocket] {line.strip()}")
                else:
                    break
                    
        except Exception as e:
            print(f"❌ WebSocket服务器启动失败: {e}")
    
    def stop_servers(self):
        """停止所有服务器"""
        print("\n🛑 正在停止服务器...")
        self.running = False
        
        if self.http_process:
            try:
                self.http_process.terminate()
                self.http_process.wait(timeout=5)
                print("✅ HTTP服务器已停止")
            except subprocess.TimeoutExpired:
                self.http_process.kill()
                print("🔥 强制停止HTTP服务器")
            except Exception as e:
                print(f"❌ 停止HTTP服务器时出错: {e}")
        
        if self.websocket_process:
            try:
                self.websocket_process.terminate()
                self.websocket_process.wait(timeout=5)
                print("✅ WebSocket服务器已停止")
            except subprocess.TimeoutExpired:
                self.websocket_process.kill()
                print("🔥 强制停止WebSocket服务器")
            except Exception as e:
                print(f"❌ 停止WebSocket服务器时出错: {e}")
    
    def run(self):
        """运行服务器管理器"""
        print("💖 心动匹配应用启动中...")
        print("=" * 50)
        
        # 检查依赖
        self.check_dependencies()
        
        # 在新线程中启动服务器
        http_thread = Thread(target=self.start_http_server, daemon=True)
        websocket_thread = Thread(target=self.start_websocket_server, daemon=True)
        
        try:
            http_thread.start()
            time.sleep(1)  # 等待HTTP服务器启动
            websocket_thread.start()
            
            # 使用 'localhost' 进行显示，因为 '0.0.0.0' 可能对用户不直观
            display_host = 'localhost' if config.HTTP_HOST == '0.0.0.0' else config.HTTP_HOST
            
            print("\n🎉 服务器启动完成!")
            print(f"🌐 API服务地址: http://{display_host}:{config.HTTP_PORT}")
            print(f"🔗 WebSocket地址: ws://{display_host}:{config.WEBSOCKET_PORT}")
            print("\n按 Ctrl+C 停止服务器")
            print("=" * 50)
            
            # 保持主线程运行
            while self.running:
                time.sleep(1)
                
                # 检查进程是否还在运行
                if self.http_process and self.http_process.poll() is not None:
                    print("⚠️  HTTP服务器意外停止")
                    break
                    
                if self.websocket_process and self.websocket_process.poll() is not None:
                    print("⚠️  WebSocket服务器意外停止")
                    break
        
        except KeyboardInterrupt:
            print("\n👋 收到停止信号...")
        except Exception as e:
            print(f"❌ 运行时错误: {e}")
        finally:
            self.stop_servers()
    
    def check_dependencies(self):
        """检查依赖"""
        required_packages = [
            'flask', 'flask-cors',  'websockets'
        ]
        
        missing_packages = []
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
            except ImportError:
                missing_packages.append(package)
        
        if missing_packages:
            print("❌ 缺少依赖包:")
            for package in missing_packages:
                print(f"   - {package}")
            print("\n请运行以下命令安装依赖:")
            print(f"pip install {' '.join(missing_packages)}")
            sys.exit(1)
        
        # 检查文件是否存在
        required_files = [
            'backend/http_server.py',
            'backend/websocket_server.py'
        ]
        
        missing_files = []
        for file_path in required_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            print("❌ 缺少必要文件:")
            for file_path in missing_files:
                print(f"   - {file_path}")
            sys.exit(1)

def signal_handler(sig, frame):
    """信号处理器"""
    print("\n👋 收到停止信号，正在关闭服务器...")
    sys.exit(0)

if __name__ == "__main__":
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动完整应用
    manager = ServerManager()
    manager.run()
