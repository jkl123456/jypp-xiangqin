import asyncio
import json
import random
from aiohttp import web, WSMsgType
import os

# 模拟用户数据库
users_db = {
    "1": {"name": "李思思", "status": "online", "avatar": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=776&q=80"},
    "2": {"name": "王悦", "status": "offline", "avatar": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=774&q=80"},
    "3": {"name": "赵雅", "status": "online", "avatar": "https://images.unsplash.com/photo-1488426862026-3ee34a7d66df?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=774&q=80"}
}

# 存储活跃的WebSocket连接
active_connections = {}
# 存储游戏状态
active_games = {}
# 存储问题列表
questions = [
    "最喜欢的旅行目的地？",
    "业余时间喜欢做什么？",
    "对未来的规划是什么？",
    "最喜欢的电影类型？",
    "最难忘的一次旅行经历？",
    "理想的约会是什么样子？",
    "最喜欢的食物是什么？",
    "如何看待工作和生活的平衡？"
]

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    user_id = None
    chat_mode = None
    room_id = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                action = data.get('type')
                
                if action == 'set_user':
                    # 设置用户信息
                    user_id = data.get('user_id')
                    chat_mode = data.get('chat_mode')
                    active_connections[user_id] = ws
                    
                    # 加入聊天室
                    if chat_mode == 'match':
                        room_id = 'match_room'
                    elif chat_mode == 'anonymous':
                        room_id = 'anonymous_room'
                    
                    # 通知用户加入成功
                    await ws.send_json({
                        'type': 'system',
                        'message': f'已加入{chat_mode}聊天室'
                    })
                
                elif action == 'chat_message':
                    # 广播聊天消息
                    message = data.get('content')
                    for uid, conn in active_connections.items():
                        if uid != user_id:  # 不发送给自己
                            await conn.send_json({
                                'type': 'chat',
                                'sender_id': user_id,
                                'sender_name': users_db.get(user_id, {}).get('name', '未知用户'),
                                'message': message
                            })
                
                elif action == 'start_game':
                    # 发起游戏请求
                    target_id = data.get('target_id')
                    if target_id in active_connections:
                        # 创建游戏
                        game_id = f"game_{user_id}_{target_id}"
                        active_games[game_id] = {
                            'player1': user_id,
                            'player2': target_id,
                            'choices': {},
                            'status': 'waiting'
                        }
                        
                        # 通知对方
                        await active_connections[target_id].send_json({
                            'type': 'game_request',
                            'game_id': game_id,
                            'from': user_id
                        })
                
                elif action == 'accept_game':
                    # 接受游戏
                    game_id = data.get('game_id')
                    if game_id in active_games:
                        active_games[game_id]['status'] = 'playing'
                        # 通知双方游戏开始
                        player1 = active_games[game_id]['player1']
                        player2 = active_games[game_id]['player2']
                        
                        if player1 in active_connections:
                            await active_connections[player1].send_json({
                                'type': 'game_start',
                                'game_id': game_id
                            })
                        
                        if player2 in active_connections:
                            await active_connections[player2].send_json({
                                'type': 'game_start',
                                'game_id': game_id
                            })
                
                elif action == 'game_choice':
                    # 处理游戏选择
                    game_id = data.get('game_id')
                    choice = data.get('choice')
                    
                    if game_id in active_games:
                        game = active_games[game_id]
                        game['choices'][user_id] = choice
                        
                        # 检查是否双方都已选择
                        if len(game['choices']) == 2:
                            # 判断胜负
                            player1 = game['player1']
                            player2 = game['player2']
                            choice1 = game['choices'][player1]
                            choice2 = game['choices'][player2]
                            
                            result = determine_winner(choice1, choice2)
                            
                            # 发送结果给双方
                            if player1 in active_connections:
                                await active_connections[player1].send_json({
                                    'type': 'game_result',
                                    'game_id': game_id,
                                    'your_choice': choice1,
                                    'opponent_choice': choice2,
                                    'result': result['player1']
                                })
                            
                            if player2 in active_connections:
                                await active_connections[player2].send_json({
                                    'type': 'game_result',
                                    'game_id': game_id,
                                    'your_choice': choice2,
                                    'opponent_choice': choice1,
                                    'result': result['player2']
                                })
                            
                            # 如果是胜者，发送问题选择
                            if result['player1'] == 'win' and player1 in active_connections:
                                await active_connections[player1].send_json({
                                    'type': 'select_question',
                                    'questions': random.sample(questions, 3)
                                })
                            
                            if result['player2'] == 'win' and player2 in active_connections:
                                await active_connections[player2].send_json({
                                    'type': 'select_question',
                                    'questions': random.sample(questions, 3)
                                })
                            
                            # 清理游戏
                            del active_games[game_id]
                
                elif action == 'send_question':
                    # 发送问题给对方
                    target_id = data.get('target_id')
                    question = data.get('question')
                    if target_id in active_connections:
                        await active_connections[target_id].send_json({
                            'type': 'question',
                            'question': question
                        })
    
    finally:
        # 清理连接
        if user_id in active_connections:
            del active_connections[user_id]
        await ws.close()
    
    return ws

def determine_winner(choice1, choice2):
    """判断划拳游戏胜负"""
    # 石头 > 剪刀, 剪刀 > 布, 布 > 石头
    rules = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
    
    if choice1 == choice2:
        return {'player1': 'draw', 'player2': 'draw'}
    elif rules[choice1] == choice2:
        return {'player1': 'win', 'player2': 'lose'}
    else:
        return {'player1': 'lose', 'player2': 'win'}

async def get_users(request):
    """获取用户列表"""
    return web.json_response(users_db)

async def index(request):
    """前端页面"""
    return web.FileResponse('./frontend/index.html')

def main():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_get('/users', get_users)
    
    # 修复静态文件服务
    app.router.add_static('/css', path='./frontend/css', name='css')
    app.router.add_static('/images', path='./frontend/images', name='images')
    app.router.add_static('/', path='./frontend', name='frontend_root')
    
    web.run_app(app, port=8765)

if __name__ == '__main__':
    main()
