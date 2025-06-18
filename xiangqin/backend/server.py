import asyncio
import websockets
import json
import random
import sqlite3
import hashlib
import os

# 初始化数据库
def init_db():
    db_path = '/www/wwwroot/xiangqin/backend/users.db'
    if not os.path.exists('backend'):
        os.makedirs('backend')
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 创建用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        nickname TEXT,
        age INTEGER,
        gender TEXT,
        interests TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 创建用户资料表
    c.execute('''CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        bio TEXT,
        location TEXT,
        education TEXT,
        profession TEXT,
        profile_image TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    conn.commit()
    conn.close()

# 初始化数据库
init_db()

# 存储连接的用户
connected_users = {}
# 聊天室：匹配聊天室
match_chat_room = set()
# 兴趣聊天室 (按主题)
interest_chat_rooms = {} # 例如: {'music': set(), 'sports': set()}
# 私聊会话
private_sessions = {} # session_id: {user_id1, user_id2}
# 游戏会话 (存储游戏对手信息)
game_sessions = {} # user_id_initiator: user_id_opponent

async def handle_message(websocket, path):
    # 用户连接时
    user_id = id(websocket)
    connected_users[user_id] = {
        'websocket': websocket,
        'username': f"用户{user_id}",
        'chat_mode': None,
        'game_state': None,
        'authenticated': False,  # 添加认证状态
        'user_id': None          # 添加用户ID
    }
    
    # 要求客户端认证
    await websocket.send(json.dumps({
        'type': 'auth_required',
        'message': '请先登录或注册'
    }))
    
    try:
        async for message in websocket:
            data = json.loads(message)
            message_type = data.get('type')
            
            # 处理不同消息类型
            if message_type == 'register':
                # 用户注册
                email = data['email']
                password = hashlib.sha256(data['password'].encode()).hexdigest()
                nickname = data.get('nickname', '')
                
                try:
                    conn = sqlite3.connect('/www/wwwroot/xiangqin/backend/users.db')
                    c = conn.cursor()
                    c.execute("INSERT INTO users (email, password, nickname) VALUES (?, ?, ?)", 
                              (email, password, nickname))
                    user_id_db = c.lastrowid
                    conn.commit()
                    
                    # 创建空资料
                    c.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id_db,))
                    conn.commit()
                    conn.close()
                    
                    await websocket.send(json.dumps({
                        'type': 'register_success',
                        'user_id': user_id_db
                    }))
                except sqlite3.IntegrityError:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': '邮箱已被注册'
                    }))
            
            elif message_type == 'login':
                # 用户登录
                email = data['email']
                password = hashlib.sha256(data['password'].encode()).hexdigest()
                
                conn = sqlite3.connect('/www/wwwroot/xiangqin/backend/users.db')
                c = conn.cursor()
                c.execute("SELECT id, nickname FROM users WHERE email=? AND password=?", (email, password))
                user = c.fetchone()
                conn.close()
                
                if user:
                    user_id_db, nickname = user
                    connected_users[user_id]['authenticated'] = True
                    connected_users[user_id]['user_id'] = user_id_db
                    connected_users[user_id]['username'] = nickname
                    
                    await websocket.send(json.dumps({
                        'type': 'login_success',
                        'user_id': user_id_db,
                        'nickname': nickname
                    }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': '邮箱或密码错误'
                    }))
            
            elif message_type == 'update_profile':
                # 更新用户资料
                if not connected_users[user_id]['authenticated']:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': '未认证用户'
                    }))
                    continue
                    
                user_id_db = connected_users[user_id]['user_id']
                age = data.get('age')
                gender = data.get('gender')
                interests = data.get('interests')
                bio = data.get('bio')
                location = data.get('location')
                education = data.get('education')
                profession = data.get('profession')
                
                conn = sqlite3.connect('/www/wwwroot/xiangqin/backend/users.db')
                c = conn.cursor()
                
                # 更新用户表
                c.execute("""UPDATE users SET 
                            age=?, gender=?, interests=?
                            WHERE id=?""", 
                         (age, gender, interests, user_id_db))
                
                # 更新资料表
                c.execute("""UPDATE profiles SET
                            bio=?, location=?, education=?, profession=?
                            WHERE user_id=?""", 
                         (bio, location, education, profession, user_id_db))
                
                conn.commit()
                conn.close()
                
                await websocket.send(json.dumps({
                    'type': 'profile_updated'
                }))
            
            elif message_type == 'set_username':
                if not connected_users[user_id]['authenticated']:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': '请先登录'
                    }))
                    continue
                    
                connected_users[user_id]['username'] = data['username']
                
            elif message_type == 'join_chat':
                chat_mode = data['mode']
                connected_users[user_id]['chat_mode'] = chat_mode
                
                if chat_mode == 'match':
                    match_chat_room.add(user_id)
                elif chat_mode == 'private':
                    target_user_id = data.get('target_user_id') # 前端应传递目标用户ID
                    if target_user_id and int(target_user_id) in connected_users:
                        target_user_id = int(target_user_id)
                        session_key = tuple(sorted((user_id, target_user_id)))
                        if session_key not in private_sessions:
                            private_sessions[session_key] = set()
                        private_sessions[session_key].add(user_id)
                        private_sessions[session_key].add(target_user_id) # 确保双方都在会话中
                        connected_users[user_id]['current_private_chat_target'] = target_user_id
                        connected_users[target_user_id]['current_private_chat_target'] = user_id
                    else:
                        await websocket.send(json.dumps({'type': 'system', 'message': '无法找到私聊对象或对象已离线。'}))
                        return # 避免后续错误

                elif chat_mode == 'interest':
                    topic = data.get('topic', 'general') # 默认为通用兴趣区
                    if topic not in interest_chat_rooms:
                        interest_chat_rooms[topic] = set()
                    interest_chat_rooms[topic].add(user_id)
                    connected_users[user_id]['chat_topic'] = topic
                
                # 发送欢迎消息
                room_name = chat_mode
                if chat_mode == 'match': room_name = '匹配'
                elif chat_mode == 'private':
                    target_id = connected_users[user_id].get('current_private_chat_target')
                    target_username = '对方'
                    if target_id and target_id in connected_users:
                        target_username = connected_users[target_id].get('username', '对方')
                    room_name = f"与 {target_username} 的私聊"
                elif chat_mode == 'interest': room_name = f"兴趣聊天室 ({connected_users[user_id].get('chat_topic', '通用')})"

                welcome_msg = {
                    'type': 'system',
                    'message': f"欢迎加入 {room_name}!"
                }
                await websocket.send(json.dumps(welcome_msg))
                
            elif message_type == 'chat_message':
                content = data['content']
                chat_mode = connected_users[user_id]['chat_mode']
                
                # 根据聊天模式广播消息
                if chat_mode == 'match':
                    for uid in match_chat_room:
                        await connected_users[uid]['websocket'].send(json.dumps({
                            'type': 'chat',
                            'sender': connected_users[user_id]['username'],
                            'message': content
                        }))
                elif chat_mode == 'private':
                    # 找到私聊会话
                    session_id = None
                    for sid, users in private_sessions.items():
                        if user_id in users:
                            session_id = sid
                            break
                    
                    if session_id:
                        for uid in private_sessions[session_id]:
                            if uid != user_id:  # 发送给会话中的其他用户
                                await connected_users[uid]['websocket'].send(json.dumps({
                            'type': 'chat',
                            'sender': connected_users[user_id]['username'],
                            'message': content
                        }))
                elif chat_mode == 'interest':
                    topic = connected_users[user_id].get('chat_topic', 'general')
                    if topic in interest_chat_rooms:
                        for uid in interest_chat_rooms[topic]:
                             await connected_users[uid]['websocket'].send(json.dumps({
                                'type': 'chat',
                                'sender': connected_users[user_id]['username'],
                                'message': content,
                                'topic': topic
                            }))
                
            elif message_type == 'start_game':
                # 开始划拳游戏
                # 前端应明确指定对手 target_user_id
                target_user_id = data.get('target_user_id') 
                if target_user_id and int(target_user_id) in connected_users:
                    target_user_id = int(target_user_id)
                    # 记录游戏会话
                    game_sessions[user_id] = target_user_id
                    game_sessions[target_user_id] = user_id # 互相记录对手
                    
                    # 向目标用户发送游戏请求
                    await connected_users[target_user_id]['websocket'].send(json.dumps({
                        'type': 'game_request',
                        'from_user_id': user_id,
                        'from_username': connected_users[user_id]['username']
                    }))
                    await websocket.send(json.dumps({'type': 'system', 'message': f"已向 {connected_users[target_user_id]['username']} 发送游戏邀请。"}))
                else:
                    await websocket.send(json.dumps({'type': 'system', 'message': '无法发起游戏：未指定对手或对手已离线。'}))
            
            elif message_type == 'accept_game':
                # 接受游戏请求
                initiator_id = data.get('initiator_id')
                if initiator_id and initiator_id in connected_users and initiator_id in game_sessions and game_sessions[initiator_id] == user_id:
                    # 双方都已准备好开始游戏
                    connected_users[user_id]['game_opponent'] = initiator_id
                    connected_users[initiator_id]['game_opponent'] = user_id
                    
                    await connected_users[initiator_id]['websocket'].send(json.dumps({
                        'type': 'game_started',
                        'opponent_username': connected_users[user_id]['username']
                    }))
                    await websocket.send(json.dumps({
                        'type': 'game_started',
                        'opponent_username': connected_users[initiator_id]['username']
                    }))
                else:
                    await websocket.send(json.dumps({'type': 'system', 'message': '接受游戏失败，对方可能已取消。'}))
            
            elif message_type == 'game_choice':
                choice = data['choice']
                opponent_id = connected_users[user_id].get('game_opponent')
                
                if opponent_id and opponent_id in connected_users:
                    connected_users[user_id]['game_state'] = choice
                    # 检查对手是否也已选择
                    if connected_users[opponent_id].get('game_state'):
                        player_choice = choice
                        opponent_choice = connected_users[opponent_id]['game_state']
                        
                        result = determine_winner(player_choice, opponent_choice)
                        
                        # 发送结果给双方
                        await websocket.send(json.dumps({
                            'type': 'game_result',
                            'result': result['player'],
                            'your_choice': player_choice,
                            'opponent_choice': opponent_choice
                        }))
                        await connected_users[opponent_id]['websocket'].send(json.dumps({
                            'type': 'game_result',
                            'result': result['opponent'],
                            'your_choice': opponent_choice,
                            'opponent_choice': player_choice
                        }))
                        
                        # 重置游戏状态
                        connected_users[user_id]['game_state'] = None
                        connected_users[opponent_id]['game_state'] = None
                        connected_users[user_id]['game_opponent'] = None
                        connected_users[opponent_id]['game_opponent'] = None
                        if user_id in game_sessions: del game_sessions[user_id]
                        if opponent_id in game_sessions: del game_sessions[opponent_id]
                        
                        # 如果玩家赢了，发送问题选择
                        if result['player'] == 'win':
                            await websocket.send(json.dumps({'type': 'select_question'}))
                        elif result['opponent'] == 'win':
                             await connected_users[opponent_id]['websocket'].send(json.dumps({'type': 'select_question'}))
                    else:
                        # 等待对方选择
                        await websocket.send(json.dumps({'type': 'system', 'message': '等待对方出拳...'}))
                        await connected_users[opponent_id]['websocket'].send(json.dumps({
                            'type': 'system', 
                            'message': f"{connected_users[user_id]['username']} 已出拳，请尽快选择！"
                        }))
                else:
                    await websocket.send(json.dumps({'type': 'system', 'message': '游戏错误：找不到对手。'}))
            
            elif message_type == 'question_selected':
                # 问题选择
                question = data['question']
                chat_mode = connected_users[user_id]['chat_mode']
                
                # 广播问题
                if chat_mode == 'match':
                    for uid in match_chat_room:
                        await connected_users[uid]['websocket'].send(json.dumps({
                            'type': 'question',
                            'sender': connected_users[user_id]['username'],
                            'question': question
                        }))
                elif chat_mode == 'private':
                    # 找到私聊会话
                    session_id = None
                    for sid, users in private_sessions.items():
                        if user_id in users:
                            session_id = sid
                            break
                    
                    if session_id:
                        for uid in private_sessions[session_id]:
                            if uid != user_id:  # 发送给会话中的其他用户
                                await connected_users[uid]['websocket'].send(json.dumps({
                                    'type': 'question',
                                    'sender': connected_users[user_id]['username'],
                                    'question': question
                                }))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # 清理用户连接
        if user_id in connected_users:
            user_info = connected_users.pop(user_id) # 获取并移除用户信息
            
            # 如果用户已认证，更新最后在线时间
            if user_info.get('authenticated') and user_info.get('user_id'):
                user_id_db = user_info['user_id']
                try:
                    conn = sqlite3.connect('/www/wwwroot/xiangqin/backend/users.db')
                    c = conn.cursor()
                    c.execute("UPDATE users SET last_online=CURRENT_TIMESTAMP WHERE id=?", (user_id_db,))
                    conn.commit()
                    conn.close()
                except:
                    pass
                
            
            if user_id in match_chat_room:
                match_chat_room.remove(user_id)
            
            # 清理兴趣聊天室
            topic = user_info.get('chat_topic')
            if topic and topic in interest_chat_rooms and user_id in interest_chat_rooms[topic]:
                interest_chat_rooms[topic].remove(user_id)
                if not interest_chat_rooms[topic]: # 如果聊天室为空则删除
                    del interest_chat_rooms[topic]

            # 清理私聊会话
                for session_key, users_in_session in list(private_sessions.items()):
                    if user_id in users_in_session:
                        users_in_session.remove(user_id)
                        if not users_in_session: # 如果会话为空则删除
                             del private_sessions[session_key]
                
                # 清理游戏会话
                if user_id in game_sessions:
                    opponent = game_sessions.pop(user_id)
                    if opponent in game_sessions and game_sessions[opponent] == user_id:
                        game_sessions.pop(opponent)
                if connected_users.get(user_id, {}).get('game_opponent'):
                    opponent_id = connected_users[user_id]['game_opponent']
                    if connected_users.get(opponent_id, {}).get('game_opponent') == user_id:
                         connected_users[opponent_id]['game_opponent'] = None
                         connected_users[opponent_id]['game_state'] = None


def determine_winner(choice1, choice2):
    """
    判断划拳游戏胜负
    """
    choices = ['rock', 'scissors', 'paper']
    results = {
        ('rock', 'scissors'): ('win', 'lose'),
        ('rock', 'paper'): ('lose', 'win'),
        ('scissors', 'paper'): ('win', 'lose'),
        ('scissors', 'rock'): ('lose', 'win'),
        ('paper', 'rock'): ('win', 'lose'),
        ('paper', 'scissors'): ('lose', 'win')
    }
    
    if choice1 == choice2:
        return {'player': 'draw', 'opponent': 'draw'}
    else:
        return {'player': results[(choice1, choice2)][0], 'opponent': results[(choice1, choice2)][1]}

async def main():
    # 添加CORS支持
    server = await websockets.serve(
        handle_message, 
        "14.103.133.136", 
        8766,  # 更改为新端口
        # 允许所有来源
        origins=None,
        # 处理非WebSocket请求
        process_request=process_request
    )
    print("WebSocket服务器启动在 ws://14.103.133.136:8766")
    await server.wait_closed()

# 处理非WebSocket请求
async def process_request(path, request_headers):
    if path == "/health":
        return http_response(200, b"OK")
    return None

# 简单HTTP响应
def http_response(status, body):
    return websockets.http.Response(
        status,
        [("Content-Type", "text/plain")],
        body
    )

if __name__ == "__main__":
    asyncio.run(main())
