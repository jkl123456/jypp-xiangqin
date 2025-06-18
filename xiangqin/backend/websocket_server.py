# -*- coding: utf-8 -*-
import asyncio
import websockets
import json
import sqlite3
import jwt
from datetime import datetime, timezone, timedelta
import logging
import random # 用于随机选择机器人
import aiohttp # 用于调用AI API
import ssl # 用于配置 SSL 上下文
import certifi # 用于提供CA证书
import time # 用于时间戳
from apscheduler.schedulers.asyncio import AsyncIOScheduler # 用于定时任务
from apscheduler.triggers.cron import CronTrigger # 用于定义cron表达式的触发器
import os
import config

# Define the base directory for the backend
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BACKEND_DIR, config.DATABASE_PATH)

# 设置日志
logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(asctime)s %(module)s:%(lineno)d %(message)s') # 修改日志级别为DEBUG并添加格式
logger = logging.getLogger(__name__)

# JWT密钥 - 应该与HTTP服务器保持一致
JWT_SECRET = 'your-secret-key-here'

# 全局变量，用于机器人轮询
current_robot_index = 0
ROBOT_DAILY_ASSIGNMENT_COUNT = 2 # 每天早上一个，晚上一个

# 新增：用于匹配聊天的数据结构
matching_queue = [] 
active_matches = {} 
REDIRECT_TIMEOUT_SECONDS = 20 # 用户重定向的超时时间（秒）

class WebSocketManager:
    def __init__(self):
        self.connections = {}
        self.rooms = {}
        self.redirecting_users = {} # user_id: (room_id, timestamp)
        self.private_chats = {} # user_id: target_user_id mapping for private chats
    
    def mark_user_redirecting(self, user_id, room_id):
        self.redirecting_users[user_id] = (room_id, time.time())
        logger.info(f"User {user_id} marked as redirecting to room {room_id}.")

    async def connect(self, websocket, user_id):
        self.connections[user_id] = websocket
        logger.info(f"User {user_id} connected with new websocket.")
        if user_id in self.redirecting_users:
            # User reconnected, was in redirecting_users.
            # We won't remove from redirecting_users here yet.
            # confirm_match_session message will handle final removal from redirecting_users.
            intended_room_id, _ = self.redirecting_users[user_id]
            logger.info(f"User {user_id} reconnected, was marked as redirecting for room {intended_room_id}. Awaiting confirm_match_session.")
    
    async def _cleanup_active_match_for_user(self, user_id_to_clean, reason_suffix="disconnected"):
        """Helper to clean up active_matches and notify partner."""
        async with match_lock:
            global active_matches
            if user_id_to_clean in active_matches:
                matched_partner_id = active_matches.pop(user_id_to_clean)
                logger.info(f"User {user_id_to_clean} removed from active_matches during cleanup ({reason_suffix}).")
                
                partner_still_in_match = False
                if matched_partner_id in active_matches and active_matches[matched_partner_id] == user_id_to_clean:
                    active_matches.pop(matched_partner_id)
                    partner_still_in_match = True
                    logger.info(f"Partner {matched_partner_id} also removed from active_matches for {user_id_to_clean} ({reason_suffix}).")
                
                if partner_still_in_match and matched_partner_id in self.connections:
                    logger.info(f"Notifying partner {matched_partner_id} that match with {user_id_to_clean} ended due to {reason_suffix}.")
                    await self.send_to_user(matched_partner_id, {
                        'type': 'match_ended',
                        'reason': f'User {user_id_to_clean} {reason_suffix}.'
                    })
                elif partner_still_in_match: # Partner was in match but not connected
                     logger.info(f"Partner {matched_partner_id} for {user_id_to_clean} was in match but is not connected, no match_ended notification sent.")
            else:
                logger.info(f"User {user_id_to_clean} was not in active_matches at time of _cleanup_active_match_for_user call ({reason_suffix}).")


    async def disconnect(self, user_id, specific_websocket_being_closed=None):
        # specific_websocket_being_closed is the actual websocket object that triggered the disconnect,
        # passed from handle_client's finally block.

        if user_id in self.redirecting_users:
            logger.info(f"User {user_id} (websocket {specific_websocket_being_closed}) disconnected but was marked as redirecting. Grace period applies.")
            # If the websocket being closed is indeed the one currently stored for this user_id,
            # it means the *old* connection from matching_lobby is closing.
            # We should remove it so that a *new* connection from chat.html can be stored cleanly.
            # If a new connection has already been established and stored, this check prevents deleting the new one.
            if user_id in self.connections and self.connections[user_id] == specific_websocket_being_closed:
                del self.connections[user_id]
                logger.info(f"Removed specific (old) websocket for redirecting user {user_id} from self.connections.")
            else:
                logger.info(f"Specific websocket for user {user_id} was not the one in self.connections or user not in connections. No deletion from self.connections here.")
            # DO NOT clear active_matches or notify partner here. Cleanup task (cleanup_redirecting_users_periodically) will handle timeouts.
            return

        # Original disconnect logic for non-redirecting users or final cleanup by timeout task
        logger.info(f"User {user_id} (websocket {specific_websocket_being_closed}) disconnected (not marked as redirecting, or final cleanup by timeout task).")
        if user_id in self.connections and self.connections[user_id] == specific_websocket_being_closed:
            del self.connections[user_id] # Remove current connection if it's the one being closed
            logger.info(f"Removed specific websocket for user {user_id} from self.connections during final cleanup.")
        elif user_id in self.connections: # A different websocket is now associated with this user_id
            logger.warning(f"User {user_id} disconnected, but self.connections[{user_id}] is a different websocket object. Not deleting the current one here.")
        else: # User not in self.connections
            logger.info(f"User {user_id} not found in self.connections during final disconnect.")
        
        # Clean from matching_queue
        
        # Clean from matching_queue
        async with match_lock:
            global matching_queue
            original_queue_len = len(matching_queue)
            matching_queue[:] = [u for u in matching_queue if u['user_id'] != user_id]
            if len(matching_queue) < original_queue_len:
                logger.info(f"User {user_id} removed from matching_queue due to disconnect.")
        
        # Clean from active_matches and notify partner
        await self._cleanup_active_match_for_user(user_id) # Default reason "disconnected"
        
        # Clean from private_chats
        if user_id in self.private_chats:
            del self.private_chats[user_id]
            logger.info(f"User {user_id} removed from private_chats due to disconnect.")

    async def join_room(self, user_id, room_name):
        if room_name not in self.rooms:
            self.rooms[room_name] = set()
        self.rooms[room_name].add(user_id)
        logger.info(f"User {user_id} joined room {room_name}")
    
    async def leave_room(self, user_id, room_name):
        if room_name in self.rooms:
            self.rooms[room_name].discard(user_id)
            if not self.rooms[room_name]:
                del self.rooms[room_name]
        logger.info(f"User {user_id} left room {room_name}")
    
    async def send_to_user(self, user_id, message):
        logger.debug(f"Attempting to send to user {user_id}. Connection exists: {user_id in self.connections}. Message: {json.dumps(message)}")
        if user_id in self.connections:
            websocket = self.connections[user_id]
            if websocket.closed:
                logger.warning(f"WebSocket connection for user {user_id} is already closed. Cannot send message.")
                await self.disconnect(user_id)
                return False
            try:
                await websocket.send(json.dumps(message))
                logger.debug(f"Successfully sent message to user {user_id}.")
                return True
            except websockets.exceptions.ConnectionClosed:
                await self.disconnect(user_id) 
                return False
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")
                await self.disconnect(user_id) 
                return False
        return False
    
    async def send_to_room(self, room_name, message, exclude_user=None):
        logger.debug(f"Attempting to send to room '{room_name}'. Room exists: {room_name in self.rooms}. Message: {json.dumps(message)}")
        if room_name not in self.rooms:
            logger.warning(f"Room '{room_name}' not found in self.rooms. Cannot send message.")
            return
        
        current_users_in_room = list(self.rooms.get(room_name, set()))
        logger.debug(f"Users in room '{room_name}': {current_users_in_room}. exclude_user: {exclude_user}")
        if not current_users_in_room:
            logger.warning(f"No users in room '{room_name}'. Cannot send message.")
            return

        disconnected_users = []
        for user_id_in_room in current_users_in_room: 
            if exclude_user and user_id_in_room == exclude_user:
                logger.debug(f"Skipping sending message to excluded user {user_id_in_room} in room {room_name}.")
                continue
            
            logger.debug(f"Preparing to send message to user {user_id_in_room} in room {room_name}.")
            success = await self.send_to_user(user_id_in_room, message)
            if not success:
                logger.warning(f"Failed to send message to user {user_id_in_room} in room {room_name}. Will mark for removal from room.")
                disconnected_users.append(user_id_in_room)
            else:
                logger.debug(f"Successfully queued/sent message to user {user_id_in_room} in room {room_name}.")
                
        if disconnected_users:
            logger.info(f"Found disconnected users in room '{room_name}': {disconnected_users}. Removing them.")
            for disconnected_user_id in disconnected_users:
                if room_name in self.rooms and disconnected_user_id in self.rooms[room_name]: # Check again before leaving
                     await self.leave_room(disconnected_user_id, room_name)
                     logger.info(f"User {disconnected_user_id} removed from room {room_name} after send failure.")

ws_manager = WebSocketManager()
match_lock = asyncio.Lock()
matchmaking_task = None

def verify_token(token):
    try:
        if token.startswith('Bearer '):
            token = token[7:]
        data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return data['user_id']
    except:
        return None

def get_user_info(user_id, full_info=False):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if full_info:
            c.execute("SELECT id, nickname, avatar, gender, city, province, is_robot FROM users WHERE id=?", (user_id,))
        else:
            c.execute("SELECT id, nickname, avatar, is_robot FROM users WHERE id=?", (user_id,))
        result = c.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        logger.error(f"Error getting user info for {user_id}: {e}")
    return None

def save_message(sender_id, receiver_id=None, room_id=None, message=None):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO chat_messages (sender_id, receiver_id, room_id, message, created_at) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (sender_id, receiver_id, room_id, message, datetime.now(timezone.utc).isoformat()))
        message_id = c.lastrowid
        
        # 如果是私聊消息，为接收者添加未读消息记录
        if receiver_id and receiver_id != sender_id: # 确保不是给自己发消息
            try:
                c.execute("""INSERT INTO unread_messages (user_id, sender_id, message_id, created_at) 
                             VALUES (?, ?, ?, ?)""",
                          (receiver_id, sender_id, message_id, datetime.now(timezone.utc).isoformat()))
                logger.info(f"Inserted unread message record for user {receiver_id} from sender {sender_id}, message_id {message_id}. Rowcount: {c.rowcount}")
            except Exception as e_unread:
                logger.error(f"Error inserting unread message record for user {receiver_id} from sender {sender_id}: {e_unread}")
        
        conn.commit()
        conn.close()
        return message_id # 返回消息ID，以便其他地方使用
    except Exception as e:
        logger.error(f"Error saving message: {e}")
    return False

def mark_messages_as_read(user_id, sender_id):
    """标记来自特定发送者的所有未读消息为已读"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("""DELETE FROM unread_messages 
                     WHERE user_id = ? AND sender_id = ?""",
                  (user_id, sender_id))
        deleted_count = c.rowcount
        conn.commit()
        conn.close()
        logger.info(f"Marked {deleted_count} messages as read for user {user_id} from sender {sender_id}")
        return deleted_count
    except Exception as e:
        logger.error(f"Error marking messages as read: {e}")
    return 0

def get_unread_count(user_id):
    """获取用户的总未读消息数量"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("""SELECT COUNT(DISTINCT sender_id) FROM unread_messages WHERE user_id = ?""", (user_id,))
        # 改为获取有多少个不同的发送者有未读消息，或者直接获取总数 COUNT(*)
        # 这里我们先用 COUNT(*) 获取总未读消息数
        c.execute("""SELECT COUNT(*) FROM unread_messages WHERE user_id = ?""", (user_id,))
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
    return 0

def get_unread_count_by_sender(user_id, sender_id):
    """获取用户来自特定发送者的未读消息数量"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM unread_messages 
                     WHERE user_id = ? AND sender_id = ?""", (user_id, sender_id))
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error getting unread count by sender: {e}")
    return 0

def record_match_in_db(user_id1, user_id2, status='matched'):
    conn = None # Initialize conn to None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO matches (user_id1, user_id2, status) VALUES (?, ?, ?)",
                  (user_id1, user_id2, status))
        conn.commit()
        logger.info(f"Recorded system match between {user_id1} and {user_id2} in DB with status '{status}'.")
        return True
    except Exception as e:
        logger.error(f"Error recording match between {user_id1} and {user_id2} in DB: {e}")
        return False
    finally:
        if conn:
            conn.close()

async def get_ai_response(messages):
    try:
        headers = {
            'Authorization': f'Bearer {config.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json'
        }
        data = { 'model': config.DEEPSEEK_MODEL, 'messages': messages, 'max_tokens': 200, 'temperature': 0.7 }
        # 使用 certifi提供的CA证书创建SSL上下文
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(config.DEEPSEEK_API_URL, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['choices'][0]['message']['content'].strip()
                else:
                    logger.error(f"AI API error: {response.status} - {await response.text()}")
                    return None
    except Exception as e:
        logger.error(f"Error calling AI API: {e}")
    return None

def get_recent_chat_history(user_id1, user_id2, limit=10):
    """获取两个用户之间最近的聊天记录"""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # 查询双方的聊天记录，并按时间倒序排列
        c.execute("""
            SELECT sender_id, message, created_at
            FROM chat_messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id1, user_id2, user_id2, user_id1, limit))
        history = [dict(row) for row in c.fetchall()]
        conn.close()
        # 将历史记录按时间正序排列，以便AI更好地理解对话顺序
        return history[::-1] 
    except Exception as e:
        logger.error(f"Error getting chat history between {user_id1} and {user_id2}: {e}")
        if conn:
            conn.close()
        return []

def check_if_recently_greeted(conn, robot_id, real_user_id, days=7):
    """检查机器人是否在最近几天内问候过该真实用户"""
    try:
        c = conn.cursor()
        threshold_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        # 尝试查询，如果表不存在则会抛出异常
        c.execute("""
            SELECT 1 FROM robot_greetings_log
            WHERE robot_id = ? AND greeted_user_id = ? AND greeted_at >= ?
            LIMIT 1
        """, (robot_id, real_user_id, threshold_date))
        return c.fetchone() is not None
    except sqlite3.Error as e:
        # 如果表不存在，尝试创建表并假设没有打过招呼
        if "no such table" in str(e).lower() and "robot_greetings_log" in str(e).lower():
            logger.warning("Table robot_greetings_log does not exist. Attempting to create it.")
            try:
                # 重新获取游标，因为之前的可能因错误而无效
                c = conn.cursor() 
                c.execute("""
                    CREATE TABLE IF NOT EXISTS robot_greetings_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        robot_id INTEGER NOT NULL,
                        greeted_user_id INTEGER NOT NULL,
                        greeted_at TEXT NOT NULL,
                        FOREIGN KEY (robot_id) REFERENCES users(id),
                        FOREIGN KEY (greeted_user_id) REFERENCES users(id)
                    )
                """)
                conn.commit()
                logger.info("Table robot_greetings_log created successfully.")
            except sqlite3.Error as create_e:
                logger.error(f"Failed to create robot_greetings_log table: {create_e}")
            return False # 假设创建后，当前还没有记录
        else:
            # 其他数据库错误
            logger.error(f"Error checking recent greetings (robot_id={robot_id}, user_id={real_user_id}): {e}")
        return False # 出错时默认为没有打过招呼，以尝试发送

def record_greeting(conn, robot_id, real_user_id):
    """记录机器人问候事件"""
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO robot_greetings_log (robot_id, greeted_user_id, greeted_at)
            VALUES (?, ?, ?)
        """, (robot_id, real_user_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        logger.info(f"Recorded greeting from robot {robot_id} to user {real_user_id}")
    except sqlite3.Error as e:
        logger.error(f"Error recording greeting (robot_id={robot_id}, user_id={real_user_id}): {e}")

async def handle_client(websocket, path):
    user_id = None
    current_rooms = set()
    try:
        query_params = {}
        if '?' in path:
            query_string = path.split('?')[1]
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    import urllib.parse
                    query_params[key] = urllib.parse.unquote(value)
        
        token = query_params.get('token')
        if not token:
            await websocket.send(json.dumps({'type': 'error', 'message': 'Missing authentication token'}))
            return
        
        user_id = verify_token(token)
        if not user_id:
            await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid authentication token'}))
            return
        
        await ws_manager.connect(websocket, user_id)
        await websocket.send(json.dumps({'type': 'connected', 'user_id': user_id}))
        
        async for message_str in websocket: 
            try:
                data = json.loads(message_str)
                message_type = data.get('type')
                
                if message_type == 'start_matching':
                    logger.info(f"User {user_id} requested to start matching.")
                    user_full_info = get_user_info(user_id, full_info=True)
                    if user_full_info:
                        async with match_lock:
                            if user_id in active_matches:
                                await websocket.send(json.dumps({'type': 'error', 'message': 'You are already in a match.'}))
                                continue
                            if any(u['user_id'] == user_id for u in matching_queue):
                                await websocket.send(json.dumps({'type': 'error', 'message': 'You are already in the matching queue.'}))
                                continue
                            matching_queue.append({
                                'user_id': user_id, 'gender': user_full_info.get('gender'),
                                'city': user_full_info.get('city'), 'province': user_full_info.get('province'),
                                'timestamp': datetime.now(timezone.utc).timestamp(), 'websocket': websocket
                            })
                            logger.info(f"User {user_id} added to matching queue. Queue size: {len(matching_queue)}")
                            await websocket.send(json.dumps({'type': 'matching_started', 'message': 'You have been added to the matching queue.'}))
                    else:
                        await websocket.send(json.dumps({'type': 'error', 'message': 'Could not retrieve user information for matching.'}))
                
                elif message_type == 'cancel_matching':
                    logger.info(f"User {user_id} requested to cancel matching.")
                    async with match_lock:
                        original_length = len(matching_queue)
                        matching_queue[:] = [u for u in matching_queue if u['user_id'] != user_id]
                        if len(matching_queue) < original_length:
                            logger.info(f"User {user_id} removed from matching queue.")
                            await websocket.send(json.dumps({'type': 'matching_cancelled', 'message': 'You have been removed from the matching queue.'}))
                        else:
                            logger.info(f"User {user_id} not found in matching queue for cancellation.")
                            await websocket.send(json.dumps({'type': 'error', 'message': 'You were not in the matching queue.'}))

                elif message_type == 'private_message':
                    target_user_id = data.get('target_user_id')
                    message_text = data.get('message')
                    if target_user_id and message_text:
                        try:
                            target_user_id = int(target_user_id)  # 确保目标用户ID是整数
                            target_user_info = get_user_info(target_user_id, full_info=True)
                            
                            if target_user_info and target_user_info.get('is_robot') == 1:
                                logger.info(f"User {user_id} sending message to ROBOT {target_user_id}: {message_text}")
                                save_message(user_id, receiver_id=target_user_id, message=message_text)
                                sender_info = get_user_info(user_id)
                                if sender_info: 
                                    await ws_manager.send_to_user(user_id, {
                                        'type': 'private_message', 'sender_id': user_id, 'sender_name': sender_info['nickname'],
                                        'avatar': sender_info['avatar'], 'message': message_text, 
                                        'created_at': datetime.now(timezone.utc).isoformat(), 'receiver_id': target_user_id
                                    })
                                
                                # 获取最近的聊天记录
                                chat_history = get_recent_chat_history(user_id, target_user_id, limit=10)
                                
                                ai_messages = []
                                robot_personality_prompt = f"你是一个名叫{target_user_info['nickname']}的聊天伙伴。"
                                if target_user_info.get('gender') == 'female':
                                    robot_personality_prompt += "你通常表现得比较温柔、有耐心。"
                                else:
                                    robot_personality_prompt += "你通常表现得比较体贴、善解人意。"
                                robot_personality_prompt += "你的回复应该简洁自然，像真人一样对话。"
                                ai_messages.append({"role": "system", "content": robot_personality_prompt})

                                if chat_history:
                                    logger.info(f"Found {len(chat_history)} messages for context between user {user_id} and robot {target_user_id}")
                                    for msg in chat_history:
                                        if msg['sender_id'] == user_id: # 用户的消息
                                            ai_messages.append({"role": "user", "content": msg['message']})
                                        else: # 机器人的消息
                                            ai_messages.append({"role": "assistant", "content": msg['message']})
                                    # 添加当前用户发送的最新消息
                                    ai_messages.append({"role": "user", "content": message_text})
                                else:
                                    logger.info(f"No chat history found between user {user_id} and robot {target_user_id}. This is a greeting.")
                                    # 如果没有历史记录，构建一个打招呼的上下文
                                    greeting_prompt = (
                                        f"你正在和用户 {sender_info['nickname']} 开始一段新的对话。请你主动打个招呼，并尝试开启一个话题。"
                                        f"用户刚刚发送了第一条消息给你：'{message_text}'"
                                    )
                                    ai_messages.append({"role": "user", "content": greeting_prompt})
                                
                                logger.debug(f"AI messages for robot {target_user_id} (to user {user_id}): {json.dumps(ai_messages, ensure_ascii=False)}")
                                ai_response_text = await get_ai_response(ai_messages)
                                
                                final_robot_reply = ai_response_text if ai_response_text else "嗯嗯，我在听呢，你可以多说一点吗？" # 更自然的默认回复
                                if not ai_response_text:
                                    logger.warning(f"AI response was empty for robot {target_user_id} to user {user_id}. Using default reply.")

                                save_message(target_user_id, receiver_id=user_id, message=final_robot_reply)
                                await ws_manager.send_to_user(user_id, {
                                    'type': 'private_message', 'sender_id': target_user_id, 'sender_name': target_user_info['nickname'],
                                    'avatar': target_user_info['avatar'], 'message': final_robot_reply,
                                    'created_at': datetime.now(timezone.utc).isoformat(), 'receiver_id': user_id
                                })
                            else: 
                                # 发送给真实用户
                                logger.info(f"User {user_id} sending private message to user {target_user_id}: {message_text}")
                                save_message(user_id, receiver_id=target_user_id, message=message_text)
                                user_info = get_user_info(user_id)
                                
                                if user_info:
                                    message_data_to_send = {
                                        'type': 'private_message', 
                                        'sender_id': user_id, 
                                        'sender_name': user_info['nickname'],
                                        'avatar': user_info['avatar'], 
                                        'message': message_text,
                                        'created_at': datetime.now(timezone.utc).isoformat(), 
                                        'receiver_id': target_user_id
                                    }
                                    
                                    # 发送给目标用户
                                    target_send_success = await ws_manager.send_to_user(target_user_id, message_data_to_send)
                                    logger.info(f"Message sent to target user {target_user_id}: {target_send_success}")
                                    
                                    # 发送给发送者（确认消息）
                                    sender_send_success = await ws_manager.send_to_user(user_id, message_data_to_send)
                                    logger.info(f"Message confirmation sent to sender {user_id}: {sender_send_success}")
                                    
                                    if not target_send_success:
                                        logger.warning(f"Failed to send message to target user {target_user_id}. User may be offline.")
                                        # 可以选择发送错误消息给发送者
                                        await ws_manager.send_to_user(user_id, {
                                            'type': 'error',
                                            'message': f'Failed to send message to user {target_user_id}. User may be offline.'
                                        })
                                else:
                                    logger.error(f"Could not get sender info for user {user_id}")
                                    await ws_manager.send_to_user(user_id, {
                                        'type': 'error',
                                        'message': 'Failed to send message: sender info not found.'
                                    })
                        except (ValueError, TypeError):
                            logger.warning(f"User {user_id} sent private_message with invalid target_user_id: {target_user_id}")
                            await ws_manager.send_to_user(user_id, {
                                'type': 'error',
                                'message': 'Invalid target_user_id for private message.'
                            })
                    else:
                        logger.warning(f"User {user_id} sent private_message without target_user_id or message")
                        await ws_manager.send_to_user(user_id, {
                            'type': 'error',
                            'message': 'target_user_id and message are required for private_message.'
                        })
                
                elif message_type == 'join_interest_room':
                    room_name_from_message = data.get('room')
                    # 优先使用消息中的 room_name，如果不存在，则尝试从 query_params 获取
                    room_name = room_name_from_message if room_name_from_message else query_params.get('room')
                    if room_name:
                        await ws_manager.join_room(user_id, room_name)
                        current_rooms.add(room_name)
                        logger.info(f"User {user_id} explicitly joined interest room {room_name} via message.")
                        # 可以选择发送房间信息或通知其他用户
                        await ws_manager.send_to_user(user_id, {'type': 'room_joined', 'room': room_name, 'status': 'success'})
                        
                        # 更新并发送房间成员数量
                        if room_name in ws_manager.rooms:
                            member_count = len(ws_manager.rooms[room_name])
                            await ws_manager.send_to_room(room_name, {'type': 'room_info', 'room': room_name, 'memberCount': member_count})
                    else:
                        logger.warning(f"User {user_id} tried to join interest room but no room name was provided in message or query params.")
                        await ws_manager.send_to_user(user_id, {'type': 'error', 'message': 'Room name not specified for join_interest_room.'})

                elif message_type == 'initiating_redirect':
                    room_id_redirect = data.get('room_id')
                    if room_id_redirect and user_id:
                        ws_manager.mark_user_redirecting(user_id, room_id_redirect)
                        # Optionally send a confirmation back, though not strictly necessary
                        # await websocket.send(json.dumps({'type': 'redirect_acknowledged'}))
                    else:
                        logger.warning(f"User {user_id} sent initiating_redirect without room_id or user_id missing.")
                
                elif message_type == 'confirm_match_session':
                    room_id_from_client = data.get('room_id')
                    logger.info(f"User {user_id} attempting to confirm match session for room: {room_id_from_client}")
                    if room_id_from_client and room_id_from_client.startswith('private_match_'):
                        parts = room_id_from_client.split('_')
                        partner_id = None
                        if len(parts) == 4: # private_match_id1_id2
                            try:
                                u1 = int(parts[2])
                                u2 = int(parts[3])
                                partner_id = u2 if user_id == u1 else (u1 if user_id == u2 else None)
                            except ValueError:
                                logger.warning(f"Could not parse user IDs from room_id {room_id_from_client} for user {user_id}")

                        if partner_id:
                            async with match_lock: # Protect active_matches
                                # Restore active_matches. It's okay if they are already set.
                                active_matches[user_id] = partner_id
                                active_matches[partner_id] = user_id # Ensure bidirectional
                                logger.info(f"User {user_id} confirmed match session for room {room_id_from_client} with partner {partner_id}. Active matches updated/confirmed.")
                            
                            await ws_manager.join_room(user_id, room_id_from_client) # Ensure user is in the room with the new websocket
                            await websocket.send(json.dumps({'type': 'match_session_confirmed', 'room_id': room_id_from_client, 'status': 'success'}))
                            logger.info(f"Sent match_session_confirmed to user {user_id} for room {room_id_from_client}")
                            
                            # If user was in redirecting_users, remove them as they've now confirmed
                            if user_id in ws_manager.redirecting_users:
                                del ws_manager.redirecting_users[user_id]
                                logger.info(f"User {user_id} removed from redirecting_users after confirming session.")
                        else:
                            logger.warning(f"User {user_id} sent confirm_match_session for room {room_id_from_client}, but partner_id could not be determined or user is not part of this match.")
                            await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid room or match confirmation failed.'}))
                    else:
                        logger.warning(f"User {user_id} sent confirm_match_session with invalid room_id: {room_id_from_client}")
                        await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid room_id for session confirmation.'}))

                elif message_type == 'room_message':
                    room_name = data.get('room')
                    message_text = data.get('message')
                    if room_name and message_text:
                        logger.info(f"User {user_id} sending message to room {room_name}: {message_text}")
                        sender_info = get_user_info(user_id)
                        if sender_info:
                            # 保存消息到数据库 (可选，根据需求决定是否为房间消息也保存)
                            save_message(user_id, room_id=room_name, message=message_text) 
                            
                            message_payload = {
                                'type': 'room_message',
                                'room': room_name,
                                'sender_id': user_id,
                                'sender_name': sender_info['nickname'],
                                'avatar': sender_info['avatar'],
                                'message': message_text,
                                'created_at': datetime.now(timezone.utc).isoformat()
                            }
                            await ws_manager.send_to_room(room_name, message_payload) # 广播给房间所有人
                        else:
                            logger.warning(f"Could not get sender info for user {user_id} to send room message.")
                            await ws_manager.send_to_user(user_id, {'type': 'error', 'message': 'Failed to send message: user info not found.'})
                    else:
                        logger.warning(f"User {user_id} tried to send room message but room_name or message was missing.")
                        await ws_manager.send_to_user(user_id, {'type': 'error', 'message': 'Room name or message content missing.'})
                
                elif message_type == 'get_room_count':
                    room_name = data.get('room')
                    if room_name:
                        count = len(ws_manager.rooms.get(room_name, set()))
                        await websocket.send(json.dumps({
                            'type': 'room_count',
                            'room': room_name,
                            'count': count
                        }))
                        logger.debug(f"Sent room count for {room_name}: {count} to user {user_id}")
                    else:
                        logger.warning(f"User {user_id} sent get_room_count without room name")

                elif message_type == 'join_private_chat':
                    target_user_id = data.get('target_user_id')
                    if target_user_id:
                        try:
                            target_user_id = int(target_user_id)
                            # 建立私聊连接关系
                            ws_manager.private_chats[user_id] = target_user_id
                            logger.info(f"User {user_id} joined private chat with user {target_user_id}")
                            
                            # 发送确认消息
                            await websocket.send(json.dumps({
                                'type': 'private_chat_joined',
                                'target_user_id': target_user_id,
                                'status': 'success'
                            }))
                            
                            logger.info(f"User {user_id} successfully joined private chat with user {target_user_id}")
                            
                        except (ValueError, TypeError):
                            logger.warning(f"User {user_id} sent join_private_chat with invalid target_user_id: {target_user_id}")
                            await websocket.send(json.dumps({
                                'type': 'error', 
                                'message': 'Invalid target_user_id for private chat'
                            }))
                    else:
                        logger.warning(f"User {user_id} sent join_private_chat without target_user_id")
                        await websocket.send(json.dumps({
                            'type': 'error', 
                            'message': 'target_user_id is required for join_private_chat'
                        }))

                elif message_type == 'typing' or message_type == 'stop_typing':
                    target_user_id = data.get('target_user_id')
                    
                    if target_user_id:
                        try:
                            target_user_id = int(target_user_id)
                            sender_info = get_user_info(user_id)
                            if sender_info:
                                typing_payload = {
                                    'type': 'user_typing' if message_type == 'typing' else 'user_stop_typing',
                                    'user_id': user_id,
                                    'username': sender_info.get('nickname', 'Someone') 
                                }
                                # 直接发送给目标用户
                                await ws_manager.send_to_user(target_user_id, typing_payload)
                                logger.debug(f"User {user_id} ({sender_info.get('nickname')}) {message_type} to user {target_user_id}")
                        except (ValueError, TypeError):
                            logger.warning(f"User {user_id} sent {message_type} with invalid target_user_id: {target_user_id}")
                    else:
                        logger.warning(f"User {user_id} sent {message_type} without target_user_id.")

                elif message_type == 'mark_as_read':
                    sender_id_to_mark = data.get('sender_id')
                    if sender_id_to_mark:
                        try:
                            sender_id_to_mark = int(sender_id_to_mark)
                            marked_count = mark_messages_as_read(user_id, sender_id_to_mark)
                            await websocket.send(json.dumps({
                                'type': 'messages_marked_read',
                                'sender_id': sender_id_to_mark,
                                'count': marked_count
                            }))
                            # 通知客户端总未读数也更新了
                            total_unread = get_unread_count(user_id)
                            await websocket.send(json.dumps({
                                'type': 'unread_count_update', # 使用新的类型以区分
                                'count': total_unread
                            }))
                            logger.info(f"User {user_id} marked {marked_count} messages as read from sender {sender_id_to_mark}. Total unread: {total_unread}")
                        except (ValueError, TypeError):
                            logger.warning(f"User {user_id} sent mark_as_read with invalid sender_id: {sender_id_to_mark}")
                    else:
                        logger.warning(f"User {user_id} sent mark_as_read without sender_id")

                elif message_type == 'get_unread_count':
                    total_unread = get_unread_count(user_id)
                    await websocket.send(json.dumps({
                        'type': 'unread_count_update', # 统一使用 unread_count_update
                        'count': total_unread
                    }))
                    logger.debug(f"Sent unread count {total_unread} to user {user_id}")

                else:
                    logger.warning(f"Unknown message type from user {user_id}: {message_type} - Full message: {data}")
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from user {user_id}")
            except Exception as e:
                logger.error(f"Error processing message from user {user_id}: {e}")
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client {user_id if user_id else 'Unknown'} disconnected (ConnectionClosed).")
    except Exception as e:
        logger.error(f"Error in handle_client for user {user_id if user_id else 'Unknown'}: {e}")
    finally:
        if user_id:
            logger.info(f"Cleaning up for user {user_id} (websocket {websocket}) in handle_client finally block.")
            # 用户断开连接时，自动离开其加入的所有房间
            for room_name in list(current_rooms): # 使用 list 复制集合以安全迭代
                logger.info(f"User {user_id} leaving room {room_name} due to disconnect from websocket {websocket}.")
                await ws_manager.leave_room(user_id, room_name)
                # 更新并发送房间成员数量
                if room_name in ws_manager.rooms: # Check if room still exists
                    member_count = len(ws_manager.rooms[room_name])
                    await ws_manager.send_to_room(room_name, {'type': 'room_info', 'room': room_name, 'memberCount': member_count})
                # No need for an else sending memberCount 0 if room is gone, send_to_room handles non-existent rooms.


            await ws_manager.disconnect(user_id, specific_websocket_being_closed=websocket)

async def matchmaking_engine():
    """后台匹配引擎，定期尝试匹配用户"""
    while True:
        await asyncio.sleep(1)  # 每秒检查一次
        async with match_lock:
            if not matching_queue:
                continue
            
            users_to_remove_from_queue = []
            queue_snapshot = list(matching_queue)
            
            available_for_real_match = [
                u for u in queue_snapshot 
                if u['user_id'] not in active_matches and 
                   u['user_id'] not in [r['user_id'] for r in users_to_remove_from_queue]
            ]
            
            if len(available_for_real_match) >= 2:
                for i in range(len(available_for_real_match)):
                    user1_data = available_for_real_match[i]
                    if user1_data['user_id'] in active_matches or user1_data['user_id'] in [r['user_id'] for r in users_to_remove_from_queue]:
                        continue
                    real_match_found_for_user1 = False # Flag for user1
                    for j in range(i + 1, len(available_for_real_match)):
                        user2_data = available_for_real_match[j]
                        if user2_data['user_id'] in active_matches or user2_data['user_id'] in [r['user_id'] for r in users_to_remove_from_queue]:
                            continue
                        if user1_data.get('gender') == user2_data.get('gender'):
                            continue

                        current_time = datetime.now(timezone.utc).timestamp()
                        time_waited_user1 = current_time - user1_data['timestamp']
                        time_waited_user2 = current_time - user2_data['timestamp']
                        current_real_match_found = False # Renamed 'real_match_found'
                        match_type = "unknown"

                        if time_waited_user1 < 3:
                            if user1_data.get('city') and user1_data.get('city') == user2_data.get('city'):
                                current_real_match_found = True; match_type = "city (user1 < 3s)"
                        if not current_real_match_found and 3 <= time_waited_user1 < 6:
                            if user1_data.get('province') and user1_data.get('province') == user2_data.get('province'):
                                current_real_match_found = True; match_type = "province (user1 3-6s)"
                            elif time_waited_user2 < 3 and user1_data.get('city') and user1_data.get('city') == user2_data.get('city'):
                                current_real_match_found = True; match_type = "city (user1 3-6s, user2 < 3s)"
                        if not current_real_match_found and time_waited_user1 >= 6:
                            current_real_match_found = True; match_type = "national (user1 6+s)"
                            if user1_data.get('province') and user1_data.get('province') == user2_data.get('province') and time_waited_user2 < 6:
                                match_type = "province (user1 6+s, user2 < 6s)"
                            elif user1_data.get('city') and user1_data.get('city') == user2_data.get('city') and time_waited_user2 < 3:
                                match_type = "city (user1 6+s, user2 < 3s)"

                        if current_real_match_found:
                            logger.info(f"Attempting real user match ({match_type}): User {user1_data['user_id']} with User {user2_data['user_id']}")
                            room_id = f"private_match_{min(user1_data['user_id'], user2_data['user_id'])}_{max(user1_data['user_id'], user2_data['user_id'])}"
                            
                            user1_info = get_user_info(user1_data['user_id'], full_info=True)
                            user2_info = get_user_info(user2_data['user_id'], full_info=True)

                            if not (user1_info and user2_info):
                                logger.error(f"Could not retrieve full info for potential real match: {user1_data['user_id']} or {user2_data['user_id']}. Match aborted for this pair.")
                                # Users remain in queue, no active_matches set.
                                real_match_found_for_user1 = True # Mark as processed this iteration to avoid immediate re-match
                                break # Break from inner user2 loop, try next user1

                            user1_info_cleaned = {k: v for k, v in user1_info.items() if k != 'websocket'}
                            user2_info_cleaned = {k: v for k, v in user2_info.items() if k != 'websocket'}

                            sent_to_user1 = False
                            if user1_data['user_id'] in ws_manager.connections:
                                sent_to_user1 = await ws_manager.send_to_user(user1_data['user_id'], {
                                    'type': 'match_found', 'room_id': room_id,
                                    'matched_user_id': user2_data['user_id'],
                                    'matched_user_info': user2_info_cleaned
                                })
                            
                            sent_to_user2 = False
                            # Only attempt to send to user2 if user1 was successful, to avoid partial match states
                            if sent_to_user1 and user2_data['user_id'] in ws_manager.connections:
                                sent_to_user2 = await ws_manager.send_to_user(user2_data['user_id'], {
                                    'type': 'match_found', 'room_id': room_id,
                                    'matched_user_id': user1_data['user_id'],
                                    'matched_user_info': user1_info_cleaned
                                })

                            if sent_to_user1 and sent_to_user2:
                                logger.info(f"Successfully sent match_found to User {user1_data['user_id']} and User {user2_data['user_id']}.")
                                ws_manager.mark_user_redirecting(user1_data['user_id'], room_id)
                                ws_manager.mark_user_redirecting(user2_data['user_id'], room_id)
                                
                                active_matches[user1_data['user_id']] = user2_data['user_id']
                                active_matches[user2_data['user_id']] = user1_data['user_id']
                                
                                record_match_in_db(user1_data['user_id'], user2_data['user_id'], status='matched')
                                
                                users_to_remove_from_queue.append(user1_data)
                                users_to_remove_from_queue.append(user2_data)
                                logger.info(f"Users {user1_data['user_id']} and {user2_data['user_id']} marked for redirect to {room_id} and will be removed from queue.")
                            else:
                                logger.warning(f"Failed to send match_found to one or both users for real match: User1_sent: {sent_to_user1}, User2_sent: {sent_to_user2}. Match aborted for this pair.")
                                # If send failed, ws_manager.disconnect would have been called for the failed user(s).
                                # If a user was disconnected and not yet marked for redirect, they'd be cleaned from queue.
                                # No need to explicitly manage active_matches here as they are only set on full success.
                                # Users whose send succeeded but partner's failed will remain in queue if their connection is still active.
                            
                            real_match_found_for_user1 = True 
                            break # Break from inner user2 loop to process next user1 or finish
                    
                    if real_match_found_for_user1: 
                        continue # Continue to next user1 in outer loop
            
            current_time_for_robot_check = datetime.now(timezone.utc).timestamp()
            for user_data_for_robot in queue_snapshot:
                if user_data_for_robot['user_id'] in active_matches or \
                   user_data_for_robot['user_id'] in [r['user_id'] for r in users_to_remove_from_queue]:
                    continue

                time_waited = current_time_for_robot_check - user_data_for_robot['timestamp']

                if time_waited >= 10: 
                    logger.info(f"User {user_data_for_robot['user_id']} waited {time_waited:.2f}s, attempting robot match.")
                    available_robots = await get_available_robots(user_data_for_robot['user_id'], user_data_for_robot.get('gender'))
                    
                    if available_robots:
                        robot_to_match = random.choice(available_robots)
                        robot_id = robot_to_match['id']
                        logger.info(f"Attempting to match User {user_data_for_robot['user_id']} with Robot {robot_id}")
                        room_id = f"private_match_{min(user_data_for_robot['user_id'], robot_id)}_{max(user_data_for_robot['user_id'], robot_id)}"
                        
                        user_info = get_user_info(user_data_for_robot['user_id'], full_info=True)
                        robot_info = get_user_info(robot_id, full_info=True)

                        if not (user_info and robot_info):
                            logger.error(f"Could not retrieve full info for user {user_data_for_robot['user_id']} or robot {robot_id}. Robot match aborted.")
                            if user_data_for_robot['user_id'] in ws_manager.connections:
                                await ws_manager.send_to_user(user_data_for_robot['user_id'], {
                                    'type': 'error', 'message': '匹配机器人过程中发生内部错误，请稍后再试。'
                                })
                            users_to_remove_from_queue.append(user_data_for_robot) # Remove user from queue on error
                            continue # Next user in queue_snapshot

                        robot_info_cleaned = {k: v for k, v in robot_info.items() if k != 'websocket'}
                        sent_to_human_user = False
                        if user_data_for_robot['user_id'] in ws_manager.connections:
                            sent_to_human_user = await ws_manager.send_to_user(user_data_for_robot['user_id'], {
                                'type': 'match_found', 'room_id': room_id,
                                'matched_user_id': robot_id,
                                'matched_user_info': robot_info_cleaned
                            })

                        if sent_to_human_user:
                            logger.info(f"Successfully sent match_found to User {user_data_for_robot['user_id']} for robot match with {robot_id}.")
                            ws_manager.mark_user_redirecting(user_data_for_robot['user_id'], room_id)
                            active_matches[user_data_for_robot['user_id']] = robot_id # Robot side of active_matches is not strictly needed for robot
                            record_match_in_db(user_data_for_robot['user_id'], robot_id, status='matched_robot')
                                
                            robot_prompt = f"你是一个名叫{robot_info.get('nickname', '智能伙伴')}的{'温柔女性' if robot_info.get('gender') == 'female' else '体贴男性'}，喜欢和人聊天，尝试主动发起一些有趣的话题。"
                            user_summary = f"对方用户昵称是{user_info.get('nickname', '用户')}"
                            if user_info.get('city'): user_summary += f"，来自{user_info.get('city')}"
                            if user_info.get('province') and user_info.get('city') != user_info.get('province'): user_summary += f"{user_info.get('province')}"
                            user_summary += "。请你主动发起聊天，说一句开场白。"
                            ai_msg_payload = [{"role": "system", "content": robot_prompt}, {"role": "user", "content": f"你好！我们刚刚通过系统匹配认识了。{user_summary}"}]
                            
                            ai_reply = await get_ai_response(ai_msg_payload)
                            final_reply = ai_reply if ai_reply else f"你好，{user_info.get('nickname', '朋友')}！很高兴认识你。"
                            
                            if not ai_reply: logger.warn(f"AI response failed for robot {robot_id}, using default.")
                            else: logger.info(f"AI message for {robot_id} to {user_data_for_robot['user_id']}: {final_reply}")
                            
                            save_message(robot_id, receiver_id=user_data_for_robot['user_id'], message=final_reply)
                            await ws_manager.send_to_user(user_data_for_robot['user_id'], {
                                'type': 'private_message', 'sender_id': robot_id, 'sender_name': robot_info['nickname'],
                                'avatar': robot_info['avatar'], 'message': final_reply,
                                'created_at': datetime.now(timezone.utc).isoformat(), 'receiver_id': user_data_for_robot['user_id']
                            })
                            users_to_remove_from_queue.append(user_data_for_robot)
                            logger.info(f"User {user_data_for_robot['user_id']} marked for redirect to {room_id} with robot {robot_id} and will be removed from queue.")
                        else:
                            logger.warning(f"Failed to send match_found to User {user_data_for_robot['user_id']} for robot match. Match aborted.")
                            # ws_manager.disconnect would have been called if send failed.
                            # User might be removed from queue by that disconnect if not yet marked redirecting.
                            # No active_matches set for this failed attempt.
                            # If user still in queue and connection is live, they will be processed again.
                            # To ensure they are removed if the send failed, we can add them to users_to_remove_from_queue
                            # if they are not already scheduled for removal by a disconnect.
                            if user_data_for_robot['user_id'] not in [u['user_id'] for u in users_to_remove_from_queue]:
                                users_to_remove_from_queue.append(user_data_for_robot)


                    else: # No available robots
                        logger.warning(f"No available robots for user {user_data_for_robot['user_id']} after timeout. Notifying and removing.")
                        if user_data_for_robot['user_id'] in ws_manager.connections:
                            await ws_manager.send_to_user(user_data_for_robot['user_id'], {
                                'type': 'error', 'message': '当前没有可匹配的智能伙伴，请稍后再试。'
                            })
                        users_to_remove_from_queue.append(user_data_for_robot) 

            if users_to_remove_from_queue:
                user_ids_processed_this_round = list(set(u['user_id'] for u in users_to_remove_from_queue))
                matching_queue[:] = [u for u in matching_queue if u['user_id'] not in user_ids_processed_this_round]
                logger.info(f"Removed users {user_ids_processed_this_round} from matching queue. New queue size: {len(matching_queue)}")

async def get_available_robots(requesting_user_id, requesting_user_gender):
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT id, nickname, avatar, gender FROM users WHERE is_robot = 1"
        if requesting_user_gender:
            if requesting_user_gender.lower() == 'male': query += " AND gender = 'female'"
            elif requesting_user_gender.lower() == 'female': query += " AND gender = 'male'"
        c.execute(query)
        robots = [dict(row) for row in c.fetchall()]
        active_robot_ids = set(v for k, v in active_matches.items() if get_user_info(v) and get_user_info(v).get('is_robot'))
        robots = [r for r in robots if r['id'] not in active_robot_ids]
        logger.info(f"Found {len(robots)} available robots for user {requesting_user_id} (gender: {requesting_user_gender}).")
        return robots
    except Exception as e:
        logger.error(f"Error getting available robots: {e}")
        return []
    finally:
        if conn: conn.close()

async def send_robot_greeting_messages():
    """
    定时任务，选择机器人向真实用户发送问候消息。
    每个被选中的机器人会尝试向一个最近未被自己问候过的异性真实用户发送消息。
    """
    global current_robot_index
    logger.info("--- Starting scheduled job: send_robot_greeting_messages ---")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor() # 获取游标

        # 1. 获取所有机器人用户
        c.execute("SELECT id, nickname, avatar, gender FROM users WHERE is_robot = 1 ORDER BY id")
        all_robots = [dict(row) for row in c.fetchall()]
        num_robots = len(all_robots)
        logger.info(f"Found {num_robots} total robots in the database.")

        if num_robots == 0:
            logger.warning("No robots found in the database. Skipping greeting messages.")
            if conn: conn.close()
            return
        
        # 2. 选择 ROBOT_DAILY_ASSIGNMENT_COUNT 个机器人进行轮询
        robots_for_this_cycle = []
        selected_robot_ids_this_cycle = set() 
        
        start_index_this_run = current_robot_index % num_robots # 记录本次运行的起始索引
        robots_considered_count = 0 # 记录考虑过的机器人数量，防止无限循环

        while len(robots_for_this_cycle) < ROBOT_DAILY_ASSIGNMENT_COUNT and robots_considered_count < num_robots:
            robot_to_assign = all_robots[current_robot_index % num_robots]
            if robot_to_assign['id'] not in selected_robot_ids_this_cycle:
                robots_for_this_cycle.append(robot_to_assign)
                selected_robot_ids_this_cycle.add(robot_to_assign['id'])
            current_robot_index = (current_robot_index + 1) % num_robots # 确保索引循环
            robots_considered_count += 1
            # 如果轮询了一圈 (current_robot_index 回到了本次运行的 start_index_this_run)
            # 并且选中的机器人数量仍小于 ROBOT_DAILY_ASSIGNMENT_COUNT，
            # 这意味着机器人总数小于 ROBOT_DAILY_ASSIGNMENT_COUNT，此时已选完所有机器人。
            if current_robot_index == start_index_this_run and len(robots_for_this_cycle) < ROBOT_DAILY_ASSIGNMENT_COUNT:
                if len(robots_for_this_cycle) == num_robots: # 确保所有机器人已被添加
                    logger.info(f"All {num_robots} robots have been selected as ROBOT_DAILY_ASSIGNMENT_COUNT ({ROBOT_DAILY_ASSIGNMENT_COUNT}) is greater or equal.")
                    break 

        logger.info(f"Selected {len(robots_for_this_cycle)} robots for this cycle: {[r['nickname'] for r in robots_for_this_cycle]}. Next global start index: {current_robot_index}")

        if not robots_for_this_cycle:
            logger.info("No robots assigned for this greeting cycle.")
            if conn: conn.close()
            return

        # 3. 获取所有真实用户
        c.execute("SELECT id, nickname, gender, city, province FROM users WHERE is_robot = 0")
        real_users = [dict(row) for row in c.fetchall()]
        num_real_users = len(real_users)
        logger.info(f"Found {num_real_users} real users to potentially greet.")

        if not real_users:
            logger.info("No real users found to send greetings to.")
            if conn: conn.close()
            return

        for robot_info in robots_for_this_cycle:
            robot_id = robot_info['id']
            robot_nickname = robot_info['nickname']
            robot_gender = robot_info['gender']
            
            greeted_in_this_cycle_by_this_robot = False 

            # 打乱真实用户列表，以便更随机地选择目标
            random.shuffle(real_users)

            for real_user in real_users:
                if greeted_in_this_cycle_by_this_robot: 
                    break # 此机器人已在此次任务中成功问候一个用户

                real_user_id = real_user['id']
                real_user_nickname = real_user['nickname']
                real_user_gender = real_user['gender']

                is_opposite_gender = (robot_gender == 'male' and real_user_gender == 'female') or \
                                     (robot_gender == 'female' and real_user_gender == 'male')
                
                if is_opposite_gender:
                    # 移除 check_if_recently_greeted 的调用
                    logger.info(f"Robot {robot_nickname} (ID: {robot_id}) preparing to greet User {real_user_nickname} (ID: {real_user_id}).")

                    robot_personality_prompt = (
                        f"你是一个名叫 {robot_nickname} 的AI聊天伙伴，你的性别是{robot_gender}。"
                            "你正在主动给一位新朋友发送问候消息。"
                            "你的目标是发起一段轻松愉快的对话，避免过于正式或刻板。"
                            "请根据以下用户信息生成一句自然的开场白，可以尝试问一个开放性的问题来鼓励对方回复。"
                        )
                        
                    ai_messages = [
                        {"role": "system", "content": robot_personality_prompt},
                        {"role": "user", "content": f"用户信息：昵称是 {real_user_nickname}，性别是 {real_user_gender}，来自 {real_user.get('city', '一个有趣的地方')}。请你主动打个招呼，并尝试开启一个话题。"}
                    ]

                    greeting_message_text = await get_ai_response(ai_messages)

                    if not greeting_message_text:
                        greeting_message_text = f"你好 {real_user_nickname}，今天过得怎么样呀？😊" 
                        logger.warning(f"AI response failed for robot {robot_id} greeting user {real_user_id}. Using default greeting.")
                    
                    message_payload = {
                        'type': 'private_message',
                        'sender_id': robot_id,
                        'sender_name': robot_info['nickname'],
                        'avatar': robot_info['avatar'],
                        'message': greeting_message_text,
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'receiver_id': real_user_id
                    }
                    
                    send_success = await ws_manager.send_to_user(real_user_id, message_payload)
                    if send_success:
                        save_message(sender_id=robot_id, receiver_id=real_user_id, message=greeting_message_text)
                        # 移除 record_greeting 的调用
                        logger.info(f"Robot {robot_nickname} (ID: {robot_id}) successfully sent greeting to User {real_user_nickname} (ID: {real_user_id}). Message: '{greeting_message_text}'")
                        greeted_in_this_cycle_by_this_robot = True 
                    else:
                        logger.warning(f"Failed to send greeting from Robot {robot_id} to User {real_user_id}. User might be offline.")
                # 移除了 else 分支 (原本用于跳过已打招呼的用户)
                else:
                    pass # Same gender or self, skip
            # Corrected indentation for the 'if' statement below
            if not greeted_in_this_cycle_by_this_robot:
                logger.info(f"Robot {robot_nickname} (ID: {robot_id}) did not find a suitable user to greet in this cycle or failed to send.")

    except sqlite3.Error as e:
        logger.error(f"Database error in send_robot_greeting_messages: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in send_robot_greeting_messages: {e}", exc_info=True)
    finally:
        if conn: # Ensure conn is not None before trying to access total_changes or close
            try:
                # Check if connection is still usable, e.g., by checking total_changes
                # This is a bit of a heuristic; a more robust check might be needed if errors persist
                if conn.total_changes >= -1: # -1 can be initial state for some drivers if no changes
                     pass 
            except sqlite3.Error: # If .total_changes itself errors out (e.g. conn closed by other means)
                logger.warning("Connection was already closed or unusable before explicit close in finally.")
                conn = None # Set to None to prevent further attempts to use it
            
            if conn: # If still considered usable
                conn.close()
                logger.debug("Database connection closed in send_robot_greeting_messages.")
        logger.info("--- Finished scheduled job: send_robot_greeting_messages ---")


async def main():
    logger.info(f"Starting WebSocket server on {config.WEBSOCKET_HOST}:{config.WEBSOCKET_PORT}")
    start_server_task = websockets.serve(
        handle_client, config.WEBSOCKET_HOST, config.WEBSOCKET_PORT, ping_interval=20, ping_timeout=10
    )
    server = await start_server_task
    logger.info("WebSocket server started successfully.")

    global matchmaking_task
    matchmaking_task = asyncio.create_task(matchmaking_engine())
    matchmaking_task.set_name("MatchmakingEngine")
    logger.info("Matchmaking engine started.")

    redirect_cleanup_task = asyncio.create_task(cleanup_redirecting_users_periodically())
    redirect_cleanup_task.set_name("RedirectCleanupTask")
    logger.info("Redirecting users cleanup task started.")

    # 初始化并启动定时任务调度器
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    # 每天早上 9 点 和 晚上 8 点 执行
    scheduler.add_job(send_robot_greeting_messages, CronTrigger(hour='9,20', minute='0')) 
    # 为了测试方便，暂时设置为每2分钟执行一次。实际部署时应改回上面的cron。
    # scheduler.add_job(send_robot_greeting_messages, CronTrigger(minute='*/2')) 
    scheduler.start()
    logger.info("APScheduler started for robot greetings.")

    try:
        # Keep the server running until it's closed or an interrupt occurs
        await server.wait_closed()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down server and tasks...")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
    finally:
        logger.info("Starting graceful shutdown of tasks...")
        tasks_to_cancel = [matchmaking_task, redirect_cleanup_task]
        # 关闭调度器
        if scheduler and scheduler.running:
            logger.info("Shutting down APScheduler...")
            scheduler.shutdown(wait=False) # use wait=False for asyncio
            logger.info("APScheduler shut down.")

        for task in tasks_to_cancel:
            if task and not task.done():
                logger.info(f"Cancelling task {task.get_name()}...")
                task.cancel()
                try:
                    await task  # Wait for task to acknowledge cancellation
                except asyncio.CancelledError:
                    logger.info(f"Task {task.get_name()} was cancelled successfully.")
                except Exception as e_task:
                    logger.error(f"Error during cancellation of task {task.get_name()}: {e_task}", exc_info=True)
            else:
                logger.info(f"Task {task.get_name()} was already done or None.")
        
        if server:
            logger.info("Closing WebSocket server...")
            server.close()
            await server.wait_closed() # Ensure server is closed before exiting
            logger.info("WebSocket server fully closed.")
        logger.info("Shutdown complete.")

async def cleanup_redirecting_users_periodically():
    """Periodically checks for timed-out redirecting users and cleans them up."""
    while True:
        await asyncio.sleep(REDIRECT_TIMEOUT_SECONDS / 2) # Check somewhat frequently
        now = time.time()
        
        # Create a list of users to cleanup to avoid modifying dict while iterating
        users_to_process_for_timeout = list(ws_manager.redirecting_users.keys())
        
        for user_id in users_to_process_for_timeout:
            if user_id not in ws_manager.redirecting_users: # Check if already removed by connect/confirm
                continue

            _, redirect_timestamp = ws_manager.redirecting_users[user_id]
            if now - redirect_timestamp > REDIRECT_TIMEOUT_SECONDS:
                logger.info(f"User {user_id} redirect timed out (timeout: {REDIRECT_TIMEOUT_SECONDS}s). Proceeding with full cleanup.")
                
                # Remove from redirecting list first to prevent re-entry into this logic block
                # for this specific timeout event.
                room_id_timed_out, _ = ws_manager.redirecting_users.pop(user_id)
                logger.info(f"User {user_id} removed from redirecting_users due to timeout for room {room_id_timed_out}.")
                
                # Now perform the original disconnect logic for active_matches and partner notification
                logger.info(f"Performing active match cleanup for timed-out redirecting user {user_id}.")
                # Pass a specific reason to distinguish from normal disconnects
                await ws_manager._cleanup_active_match_for_user(user_id, reason_suffix="redirect timeout")
            
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application shutdown requested.")
