from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
import jwt
import datetime
import os
import json
from functools import wraps
import uuid # For generating unique filenames
from werkzeug.utils import secure_filename # For securing filenames
import config # 导入配置文件

# Define the base directory for the backend
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# Define the project root directory (one level up from backend)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
# Define the frontend directory
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='/frontend')
# Configuration for file uploads
UPLOAD_FOLDER = os.path.join(FRONTEND_DIR, 'user_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Create upload folders if they don't exist
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'avatars'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'cards'), exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
CORS(app, resources={r"/*": {"origins": "*"}}) # 允许所有源

# JWT密钥 - 在生产环境中应该使用环境变量
JWT_SECRET = 'your-secret-key-here'
DATABASE_PATH = os.path.join(BACKEND_DIR, config.DATABASE_PATH) # 从配置文件读取数据库路径

# 数据库初始化
def init_db():
    db_path = DATABASE_PATH
    # The directory for the database is the BACKEND_DIR, which is guaranteed to exist.
    # No need to check for 'backend' folder existence here.
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 检查用户表是否存在
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    table_exists = c.fetchone()
    
    if not table_exists:
        # 创建用户表 - 扩展字段
        c.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nickname TEXT,
            age INTEGER,
            gender TEXT,
            profession TEXT,
            province TEXT,
            city TEXT,
            interests TEXT,
            bio TEXT,
            avatar TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_online TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    else:
        # 检查并添加缺失的列
        c.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in c.fetchall()]
        
        required_columns = [
            ('age', 'INTEGER'),
            ('gender', 'TEXT'),
            ('profession', 'TEXT'),
            ('province', 'TEXT'),
            ('city', 'TEXT'),
            ('interests', 'TEXT'),
            ('bio', 'TEXT'),
            ('avatar', 'TEXT'),
            ('last_online', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
            ('is_robot', 'INTEGER DEFAULT 0'), # 添加 is_robot 列
            ('background', 'TEXT') # 添加 background 列
        ]
        
        for column_name, column_type in required_columns:
            if column_name not in columns:
                try:
                    c.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
                    print(f"Added column {column_name} to users table")
                except sqlite3.OperationalError as e:
                    print(f"Error adding column {column_name}: {e}")
    
    # 创建用户卡片表
    c.execute('''CREATE TABLE IF NOT EXISTS user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        image_url TEXT,
        order_index INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # 创建匹配表
    c.execute('''CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id1 INTEGER,
        user_id2 INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id1) REFERENCES users(id),
        FOREIGN KEY(user_id2) REFERENCES users(id)
    )''')
    
    # 创建聊天记录表
    c.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        room_id TEXT,
        message TEXT,
        message_type TEXT DEFAULT 'text',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(sender_id) REFERENCES users(id),
        FOREIGN KEY(receiver_id) REFERENCES users(id)
    )''')
    
    # 创建兴趣聊天室表
    c.execute('''CREATE TABLE IF NOT EXISTS interest_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 创建未读消息表
    c.execute('''CREATE TABLE IF NOT EXISTS unread_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(sender_id) REFERENCES users(id),
        FOREIGN KEY(message_id) REFERENCES chat_messages(id)
    )''')
    
    # 插入默认兴趣聊天室
    default_rooms = [
        ('音乐', '分享你喜欢的音乐，讨论各种音乐话题'),
        ('电影', '电影推荐、影评分享、演员讨论'),
        ('旅行', '旅行攻略、景点推荐、旅行故事'),
        ('美食', '美食分享、烹饪交流、餐厅推荐'),
        ('运动', '健身、户外运动、体育赛事讨论'),
        ('读书', '图书推荐、读书心得、文学交流'),
        ('游戏', '游戏攻略、电竞讨论、手游分享'),
        ('科技', '最新科技、数码产品、编程技术')
    ]
    
    for room_name, room_desc in default_rooms:
        c.execute('INSERT OR IGNORE INTO interest_rooms (name, description) VALUES (?, ?)', 
                 (room_name, room_desc))
    
    conn.commit()
    conn.close()

# JWT认证装饰器
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        try:
            # 移除 "Bearer " 前缀
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            current_user_id = data['user_id']
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        
        return f(current_user_id, *args, **kwargs)
    return decorated

# 用户注册
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    nickname = data.get('nickname', '')
    
    if not email or not password:
        return jsonify({'message': '邮箱和密码不能为空'}), 400
    
    # 密码加密
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO users (email, password, nickname) VALUES (?, ?, ?)", 
                  (email, password_hash, nickname))
        user_id = c.lastrowid
        conn.commit()
        conn.close()
        
        # 生成JWT token
        token = jwt.encode({
            'user_id': user_id,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
        }, JWT_SECRET, algorithm='HS256')
        
        return jsonify({
            'message': '注册成功',
            'token': token,
            'user_id': user_id
        }), 201
        
    except sqlite3.IntegrityError:
        return jsonify({'message': '邮箱已被注册'}), 400

# 用户登录
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'message': '邮箱和密码不能为空'}), 400
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nickname FROM users WHERE email=? AND password=?", 
              (email, password_hash))
    user = c.fetchone()
    
    if user:
        user_id, nickname = user
        # 更新最后登录时间
        c.execute("UPDATE users SET last_online=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        
        # 生成JWT token
        token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
        }, JWT_SECRET, algorithm='HS256')
        
        return jsonify({
            'message': '登录成功',
            'token': token,
            'user_id': user_id,
            'nickname': nickname
        }), 200
    else:
        conn.close()
        return jsonify({'message': '邮箱或密码错误'}), 401

# 获取用户资料
@app.route('/api/profile', methods=['GET'])
@app.route('/api/user/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row # 确保可以按列名访问
    c = conn.cursor()
    
    # 获取用户基本信息
    c.execute("""SELECT id, email, nickname, age, gender, profession, province, city, 
                        interests, bio, avatar 
                 FROM users WHERE id=?""", (current_user_id,))
    user_data_row = c.fetchone()
    
    if not user_data_row:
        conn.close()
        return jsonify({'message': '用户不存在'}), 404
    
    user_data = dict(user_data_row) # 转换为字典

    # 获取用户卡片
    c.execute("SELECT image_url FROM user_cards WHERE user_id=? ORDER BY order_index", 
              (current_user_id,))
    cards = [row['image_url'] for row in c.fetchall()]
    
    # 获取统计数据
    c.execute("SELECT COUNT(*) FROM matches WHERE (user_id1=? OR user_id2=?) AND status='matched'", 
              (current_user_id, current_user_id))
    match_count = c.fetchone()[0]
    
    c.execute("""SELECT COUNT(DISTINCT 
                        CASE WHEN sender_id=? THEN receiver_id 
                             WHEN receiver_id=? THEN sender_id END)
                 FROM chat_messages 
                 WHERE (sender_id=? OR receiver_id=?) AND room_id IS NULL""", # 只统计私聊
              (current_user_id, current_user_id, current_user_id, current_user_id))
    chat_count = c.fetchone()[0]
    
    conn.close()
    
    profile = {
        'id': user_data['id'],
        'email': user_data['email'],
        'nickname': user_data['nickname'],
        'age': user_data['age'],
        'gender': user_data['gender'],
        'profession': user_data['profession'],
        'province': user_data['province'],
        'city': user_data['city'],
        'interests': user_data['interests'],
        'bio': user_data['bio'],
        'avatar': user_data['avatar'],
        'cards': cards,
        'match_count': match_count,
        'chat_count': chat_count
    }
    
    return jsonify(profile), 200

# 获取其他用户资料
@app.route('/api/user/<int:user_id>', methods=['GET'])
@token_required
def get_user_profile(current_user_id, user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 获取用户基本信息
    c.execute("""SELECT id, nickname, age, gender, profession, province, city, 
                        bio, avatar 
                 FROM users WHERE id=?""", (user_id,))
    user_data_row = c.fetchone()
    
    if not user_data_row:
        conn.close()
        return jsonify({'message': '用户不存在'}), 404
    
    user_data = dict(user_data_row)

    # 获取用户卡片
    c.execute("SELECT image_url FROM user_cards WHERE user_id=? ORDER BY order_index", 
              (user_id,))
    cards = [row['image_url'] for row in c.fetchall()]
    
    conn.close()
    
    profile = {
        'id': user_data['id'],
        'nickname': user_data['nickname'],
        'age': user_data['age'],
        'gender': user_data['gender'],
        'profession': user_data['profession'],
        'province': user_data['province'],
        'city': user_data['city'],
        'bio': user_data['bio'],
        'avatar': user_data['avatar'],
        'cards': cards
    }
    
    return jsonify(profile), 200

# 更新用户资料
@app.route('/api/profile', methods=['PUT'])
@token_required
def update_profile(current_user_id):
    data = request.json
    app.logger.info(f"Updating profile for user_id: {current_user_id}")
    app.logger.info(f"Received data for profile update: {json.dumps(data, indent=2)}") # Log entire payload
    
    received_avatar_url = data.get('avatar')
    app.logger.info(f"Received avatar URL from payload: {received_avatar_url}")

    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    fields_to_update = []
    values_to_update = []

    # 检查并添加基本信息字段到更新列表
    user_fields = ['nickname', 'age', 'gender', 'profession', 'province', 'city', 'interests', 'bio', 'avatar']
    for field in user_fields:
        if field in data: # 检查字段是否存在于请求数据中
            fields_to_update.append(f"{field}=?")
            values_to_update.append(data.get(field))
    
    if fields_to_update: # 如果有基本信息字段需要更新
        sql_update_user = f"UPDATE users SET {', '.join(fields_to_update)} WHERE id=?"
        values_to_update.append(current_user_id)
        app.logger.info(f"Executing user update SQL: {sql_update_user} with values: {tuple(values_to_update)}")
        c.execute(sql_update_user, tuple(values_to_update))

    # 更新用户卡片 (仅当 'cards' 字段在请求中明确提供时)
    if 'cards' in data:
        app.logger.info(f"Updating user cards for user_id: {current_user_id}")
        # 先删除现有卡片
        c.execute("DELETE FROM user_cards WHERE user_id=?", (current_user_id,))
        
        # 插入新卡片
        cards = data.get('cards', []) # 如果 'cards' 存在但为空数组，则会删除所有卡片
        app.logger.info(f"New cards to insert: {cards}")
        for i, card_url in enumerate(cards):
            if card_url and isinstance(card_url, str): #确保 card_url 是有效的字符串
                c.execute("INSERT INTO user_cards (user_id, image_url, order_index) VALUES (?, ?, ?)",
                          (current_user_id, card_url, i))
            else:
                app.logger.warn(f"Skipping invalid card_url at index {i}: {card_url}")
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': '资料更新成功'}), 200

# 图片上传接口
@app.route('/api/upload-image', methods=['POST'])
@token_required
def upload_image(current_user_id):
    if 'file' not in request.files:
        return jsonify({'message': 'No file part in the request'}), 400
    
    file = request.files['file']
    upload_type = request.form.get('upload_type', 'card') # 'avatar' or 'card'

    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Create a unique filename to prevent overwrites and ensure URL compatibility
        unique_suffix = uuid.uuid4().hex[:8]
        extension = filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{current_user_id}_{unique_suffix}.{extension}"

        if upload_type == 'avatar':
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'avatars', unique_filename)
            relative_url = f"/user_uploads/avatars/{unique_filename}"
        elif upload_type == 'card':
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', unique_filename)
            relative_url = f"/user_uploads/cards/{unique_filename}"
        else:
            return jsonify({'message': 'Invalid upload type'}), 400
        
        try:
            file.save(save_path)
            # The URL returned should be accessible by the client.
            # Assuming 'frontend' is served at the root, and 'user_uploads' is inside it.
            # If your Flask app serves static files from a different base, adjust accordingly.
            # For example, if frontend is at http://localhost:5000/, then the URL is correct.
            return jsonify({'message': 'File uploaded successfully', 'imageUrl': relative_url}), 200
        except Exception as e:
            app.logger.error(f"Error saving uploaded file: {e}")
            return jsonify({'message': 'Error saving file'}), 500
    else:
        return jsonify({'message': 'File type not allowed'}), 400

# 配置静态文件服务 (用于访问上传的图片)
# The `static_folder` and `static_url_path` configured for the Flask app
# should now handle serving all files from the `frontend` directory directly
# via the `/frontend` URL prefix.
# For example, a file at `frontend/images/foo.png` would be accessible at `/frontend/images/foo.png`.
# A file at `frontend/user_uploads/avatars/bar.png` would be accessible at `/frontend/user_uploads/avatars/bar.png`.

# The explicit route for `/user_uploads` might become redundant if `static_url_path` is `/` 
# and `static_folder` points to `frontend`. However, with `static_url_path='/frontend'`,
# this explicit route is still useful if we want a different URL structure for uploads,
# but it's actually covered by the main static file serving now.
# Let's comment it out to avoid potential conflicts or redundancy,
# as Flask's built-in static serving should handle `/frontend/user_uploads/...`

# We need to ensure that existing URLs like /user_uploads/avatars/xyz.png continue to work.
# The main static serving is via /frontend. So, /frontend/user_uploads/avatars/xyz.png works.
# To make /user_uploads/avatars/xyz.png work, we need this explicit route.
@app.route('/user_uploads/<path:folder>/<path:filename>')
def serve_uploaded_file(folder, filename):
    if folder not in ['avatars', 'cards']:
        return jsonify({'message': 'Invalid folder'}), 404
    
    # UPLOAD_FOLDER is already an absolute path to 'frontend/user_uploads'
    # specific_folder_path will be 'frontend/user_uploads/avatars' or 'frontend/user_uploads/cards'
    specific_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
    
    from flask import send_from_directory
    try:
        # send_from_directory expects the directory from which to serve files.
        # Here, specific_folder_path is the correct absolute path to the 'avatars' or 'cards' directory.
        return send_from_directory(specific_folder_path, filename)
    except FileNotFoundError:
        app.logger.error(f"File not found: {filename} in folder {specific_folder_path}")
        return jsonify({'message': 'File not found'}), 404

# 获取推荐用户（用于卡片滑动）
@app.route('/api/discover', methods=['GET'])
@token_required
def discover_users(current_user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 获取当前用户信息
    c.execute("SELECT gender, province, city FROM users WHERE id=?", (current_user_id,))
    current_user_row = c.fetchone()
    
    if not current_user_row:
        conn.close()
        return jsonify({'message': '用户不存在'}), 404
    
    current_user = dict(current_user_row)
    app.logger.debug(f"[discover_users] Current User ID: {current_user_id}, Info: {current_user}")
    
    # 排除已匹配和已拒绝的用户
    c.execute("""SELECT DISTINCT user_id2 FROM matches 
                 WHERE user_id1=? 
                 UNION 
                 SELECT DISTINCT user_id1 FROM matches 
                 WHERE user_id2=?""", 
              (current_user_id, current_user_id))
    excluded_users_rows = c.fetchall()
    app.logger.debug(f"[discover_users] Excluded users rows (from matches): {excluded_users_rows}")
    excluded_users = [row[0] for row in excluded_users_rows] # 确保正确获取列数据
    excluded_users.append(current_user_id)
    app.logger.debug(f"[discover_users] Final excluded_users list: {excluded_users}")
    
    # 构建查询条件 - 优先推荐异性、同城用户
    query_params = []
    
    base_query_select = """SELECT u.id, u.nickname, u.age, u.gender, u.profession, 
                                   u.province, u.city, u.bio, u.avatar, u.is_robot,
                                   (SELECT image_url FROM user_cards WHERE user_id=u.id ORDER BY order_index LIMIT 1) as main_card
                            FROM users u"""
    
    # 修改过滤条件：需要有昵称，并且 main_card 不为空
    # 机器人也可以被推荐，只要它们有 main_card
    where_clauses = [
        "u.nickname IS NOT NULL",
        "(SELECT image_url FROM user_cards WHERE user_id=u.id ORDER BY order_index LIMIT 1) IS NOT NULL",
        "(SELECT image_url FROM user_cards WHERE user_id=u.id ORDER BY order_index LIMIT 1) != ''"
    ]

    if excluded_users:
        where_clauses.append("u.id NOT IN ({})".format(','.join(['?'] * len(excluded_users))))
        query_params.extend(excluded_users)
    
    full_where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    base_query = base_query_select + full_where_clause

    # 按优先级排序：真实用户优先 > 异性 > 同城 > 同省
    # 如果 current_user['gender'] 为 None 或空，则性别比较可能不准确，但 SQL 会处理
    # 确保 current_user['gender'] 等参数存在
    current_user_gender = current_user.get('gender') if current_user else None
    current_user_city = current_user.get('city') if current_user else None
    current_user_province = current_user.get('province') if current_user else None

    order_clause_parts = ["CASE WHEN u.is_robot = 0 THEN 1 ELSE 2 END"] # 真实用户优先
    
    if current_user_gender:
        order_clause_parts.append("CASE WHEN u.gender != ? THEN 1 ELSE 2 END")
        query_params.append(current_user_gender)
    else: # 如果当前用户性别未知，则不按性别排序或按其他默认方式
        pass # 或者添加一个默认排序，例如 u.gender

    if current_user_city:
        order_clause_parts.append("CASE WHEN u.city = ? THEN 1 ELSE 2 END")
        query_params.append(current_user_city)
    
    if current_user_province:
        order_clause_parts.append("CASE WHEN u.province = ? THEN 1 ELSE 2 END")
        query_params.append(current_user_province)
        
    order_clause_parts.append("RANDOM()")
    
    order_clause = "ORDER BY " + ", ".join(order_clause_parts) + " LIMIT 15" # Changed from 20 to 15
    
    full_query = base_query + " " + order_clause
    
    # query_params 已经包含了 excluded_users 和排序参数
    
    app.logger.debug(f"[discover_users] Executing SQL: {full_query}")
    app.logger.debug(f"[discover_users] With parameters: {query_params}")
    c.execute(full_query, query_params)
    users_rows = c.fetchall()
    app.logger.debug(f"[discover_users] SQL Result (users_rows): {users_rows}")
    
    conn.close()
    
    # 格式化返回数据
    recommended_users = []
    # 添加日志，在格式化之前打印原始的 users_rows
    app.logger.debug(f"[/api/discover] Raw users_rows before formatting for user {current_user_id}: {[dict(row) for row in users_rows]}")
    for user_row in users_rows:
        user = dict(user_row)
        user_data = {
            'id': user['id'],
            'nickname': user['nickname'],
            'age': user['age'],
            'gender': user['gender'],
            'profession': user['profession'],
            'province': user['province'],
            'city': user['city'],
            'bio': user['bio'],
            'avatar': user['avatar'],
            'main_card': user['main_card']
        }
        recommended_users.append(user_data)
    
    app.logger.debug(f"[/api/discover] Formatted recommended_users for user {current_user_id}: {recommended_users}") # 修改日志内容
    return jsonify({'users': recommended_users}), 200

# 调试接口：检查数据库状态
@app.route('/api/debug/db-status', methods=['GET'])
@token_required
def debug_db_status(current_user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 获取当前用户信息
    c.execute("SELECT id, nickname, gender, city, province, is_robot FROM users WHERE id=?", (current_user_id,))
    current_user_row_data = c.fetchone() # 使用新变量名避免覆盖
    current_user = dict(current_user_row_data) if current_user_row_data else None
    
    # 获取所有用户数量
    c.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = c.fetchone()['total_users']
    
    # 获取非机器人用户数量
    c.execute("SELECT COUNT(*) as non_robot_users FROM users WHERE is_robot = 0")
    non_robot_users = c.fetchone()['non_robot_users']
    
    # 获取有昵称的非机器人用户数量
    c.execute("SELECT COUNT(*) as valid_users FROM users WHERE is_robot = 0 AND nickname IS NOT NULL")
    valid_users = c.fetchone()['valid_users']
    
    # 获取当前用户的匹配记录
    c.execute("""SELECT COUNT(*) as match_count FROM matches 
                 WHERE user_id1=? OR user_id2=?""", (current_user_id, current_user_id))
    match_count = c.fetchone()['match_count']
    
    # 获取前5个有效用户的信息
    c.execute("""SELECT id, nickname, gender, city, province, is_robot 
                 FROM users WHERE is_robot = 0 AND nickname IS NOT NULL 
                 LIMIT 5""")
    sample_users = [dict(row) for row in c.fetchall()]
    
    # 获取未读消息统计
    c.execute("SELECT COUNT(*) as total_unread FROM unread_messages WHERE user_id = ?", (current_user_id,))
    total_unread = c.fetchone()['total_unread']
    
    # 获取聊天伙伴数量
    c.execute("""SELECT COUNT(DISTINCT 
                        CASE WHEN sender_id=? THEN receiver_id 
                             WHEN receiver_id=? THEN sender_id END) as chat_partners
                 FROM chat_messages 
                 WHERE (sender_id=? OR receiver_id=?) AND room_id IS NULL""",
              (current_user_id, current_user_id, current_user_id, current_user_id))
    chat_partners = c.fetchone()['chat_partners']
    
    conn.close()
    
    debug_info = {
        'current_user': current_user,
        'database_stats': {
            'total_users': total_users,
            'non_robot_users': non_robot_users,
            'valid_users': valid_users,
            'current_user_matches': match_count,
            'current_user_unread_messages': total_unread,
            'current_user_chat_partners': chat_partners
        },
        'sample_valid_users': sample_users
    }
    
    return jsonify(debug_info), 200

# 处理滑动操作（喜欢/跳过）
@app.route('/api/swipe', methods=['POST'])
@token_required
def swipe_user(current_user_id):
    data = request.json
    target_user_id = data.get('target_user_id')
    action = data.get('action')  # 'like' or 'pass'
    
    if not target_user_id or action not in ['like', 'pass']:
        return jsonify({'message': '无效的请求参数'}), 400
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    # 检查是否已经存在匹配记录
    c.execute("""SELECT id, status FROM matches 
                 WHERE (user_id1=? AND user_id2=?) OR (user_id1=? AND user_id2=?)""",
              (current_user_id, target_user_id, target_user_id, current_user_id))
    existing_match = c.fetchone()
    
    if existing_match:
        conn.close()
        return jsonify({'message': '已经处理过该用户'}), 400
    
    # 创建匹配记录
    match_status = 'liked' if action == 'like' else 'passed'
    c.execute("INSERT INTO matches (user_id1, user_id2, status) VALUES (?, ?, ?)",
              (current_user_id, target_user_id, match_status))
    
    is_mutual_match = False
    
    # 如果是喜欢，检查对方是否也喜欢了你
    if action == 'like':
        c.execute("""SELECT id FROM matches 
                     WHERE user_id1=? AND user_id2=? AND status='liked'""",
                  (target_user_id, current_user_id))
        mutual_like = c.fetchone()
        
        if mutual_like:
            # 互相喜欢，更新状态为匹配成功
            c.execute("UPDATE matches SET status='matched' WHERE id=?", (mutual_like[0],))
            c.execute("UPDATE matches SET status='matched' WHERE user_id1=? AND user_id2=?",
                      (current_user_id, target_user_id))
            is_mutual_match = True
    
    conn.commit()
    conn.close()
    
    result = {'action': action}
    if is_mutual_match:
        result['match'] = True
        result['message'] = '恭喜！你们互相喜欢，可以开始聊天了！'
    
    return jsonify(result), 200

# 获取兴趣聊天室列表
@app.route('/api/interest-rooms', methods=['GET'])
def get_interest_rooms():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, name, description FROM interest_rooms ORDER BY name")
    rooms_rows = c.fetchall()
    conn.close()
    
    room_list = [dict(room) for room in rooms_rows]
    
    return jsonify({'rooms': room_list}), 200

# 获取匹配的聊天列表
@app.route('/api/chats', methods=['GET'])
@token_required
def get_chat_list(current_user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = """
    SELECT 
        u.id as user_id,
        u.nickname,
        u.avatar,
        (SELECT image_url FROM user_cards WHERE user_id=u.id ORDER BY order_index LIMIT 1) as main_card,
        MAX(cm.created_at) as last_message_time,
        (SELECT message FROM chat_messages 
         WHERE ((sender_id = u.id AND receiver_id = :current_user_id) OR (sender_id = :current_user_id AND receiver_id = u.id))
               AND room_id IS NULL
         ORDER BY created_at DESC LIMIT 1) as last_message,
        (SELECT COUNT(*) FROM unread_messages um WHERE um.user_id = :current_user_id AND um.sender_id = u.id) as unread_count,
        (SELECT MAX(created_at) FROM unread_messages um_sort WHERE um_sort.user_id = :current_user_id AND um_sort.sender_id = u.id) as last_unread_time
    FROM users u
    JOIN (
        SELECT DISTINCT CASE WHEN sender_id = :current_user_id THEN receiver_id ELSE sender_id END as other_user
        FROM chat_messages
        WHERE (sender_id = :current_user_id OR receiver_id = :current_user_id) AND room_id IS NULL
        UNION
        SELECT DISTINCT CASE WHEN user_id1 = :current_user_id THEN user_id2 ELSE user_id1 END as other_user
        FROM matches
        WHERE (user_id1 = :current_user_id OR user_id2 = :current_user_id) AND (status = 'matched' OR status = 'matched_robot')
    ) AS chat_partners ON u.id = chat_partners.other_user
    LEFT JOIN chat_messages cm ON ((cm.sender_id = u.id AND cm.receiver_id = :current_user_id) OR (cm.sender_id = :current_user_id AND cm.receiver_id = u.id)) AND cm.room_id IS NULL
    WHERE u.id != :current_user_id
    GROUP BY u.id
    ORDER BY 
        CASE WHEN last_unread_time IS NOT NULL THEN 1 ELSE 2 END, 
        COALESCE(last_unread_time, last_message_time) DESC,
        last_message_time DESC
    """
    c.execute(query, {'current_user_id': current_user_id})
    
    chats_rows = c.fetchall()
    app.logger.debug(f"[/api/chats] Fetched chats_rows for user {current_user_id}: {chats_rows}") # 添加日志
    conn.close()
    
    chat_list = [dict(row) for row in chats_rows]
    for chat in chat_list:
        if not chat['avatar'] and chat['main_card']: # 如果没有头像，使用主卡片作为头像
            chat['avatar'] = chat['main_card']
        if not chat['last_message']:
            chat['last_message'] = '开始聊天吧！'
            
    return jsonify({'chats': chat_list}), 200

# 获取聊天历史
@app.route('/api/chat/history', methods=['GET'])
@token_required
def get_chat_history(current_user_id):
    other_user_id = request.args.get('user_id', type=int)
    page = request.args.get('page', 1, type=int) # Frontend should ideally only request page 1
    per_page = 80 # Changed from 50 to 80
    offset = (page - 1) * per_page
    
    if not other_user_id:
        return jsonify({'message': '缺少用户ID参数'}), 400
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""SELECT sender_id, message, created_at FROM chat_messages 
                 WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
                 AND room_id IS NULL
                 ORDER BY created_at DESC LIMIT ? OFFSET ?""",
              (current_user_id, other_user_id, other_user_id, current_user_id, per_page, offset))
    
    messages_rows = c.fetchall()
    conn.close()
    
    message_list = []
    for msg_row in messages_rows:
        msg = dict(msg_row)
        message_list.append({
            'sender_id': msg['sender_id'],
            'message': msg['message'],
            'created_at': msg['created_at'],
            'is_own': msg['sender_id'] == current_user_id
        })
    
    # 反转顺序，最新的在最后
    message_list.reverse()
    
    return jsonify(message_list), 200

# 获取兴趣聊天室历史消息
@app.route('/api/chat/room-history', methods=['GET'])
@token_required
def get_room_chat_history(current_user_id):
    room_name = request.args.get('room')
    page = request.args.get('page', 1, type=int) # Frontend should ideally only request page 1 if we want fixed latest N
    per_page = 150 # Changed from 50 to 150
    offset = (page - 1) * per_page
    
    if not room_name:
        return jsonify({'message': '缺少房间参数'}), 400
    
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""SELECT cm.sender_id, cm.message, cm.created_at, u.nickname, u.avatar
                 FROM chat_messages cm
                 JOIN users u ON cm.sender_id = u.id
                 WHERE cm.room_id = ?
                 ORDER BY cm.created_at DESC LIMIT ? OFFSET ?""",
              (room_name, per_page, offset))
    
    messages_rows = c.fetchall()
    conn.close()
    
    message_list = [dict(msg) for msg in messages_rows]
    
    # 反转顺序，最新的在最后
    message_list.reverse()
    
    return jsonify(message_list), 200

# 获取当前用户总未读消息数
@app.route('/api/unread-count', methods=['GET'])
@token_required
def get_total_unread_count(current_user_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM unread_messages WHERE user_id = ?", (current_user_id,))
        count = c.fetchone()[0]
        conn.close()
        return jsonify({'unread_count': count}), 200
    except Exception as e:
        app.logger.error(f"Error in /api/unread-count for user {current_user_id}: {e}")
        return jsonify({'message': 'Error fetching unread count', 'error': str(e)}), 500

# 获取用于首页球体的昵称列表
@app.route('/api/nicknames_for_sphere', methods=['GET'])
def get_nicknames_for_sphere():
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        # 选择所有非空且不为空字符串的昵称
        c.execute("SELECT nickname FROM users WHERE nickname IS NOT NULL AND nickname != ''")
        nicknames_tuples = c.fetchall()
        conn.close()
        
        nicknames_list = [item[0] for item in nicknames_tuples]
        
        return jsonify({'nicknames': nicknames_list}), 200
    except Exception as e:
        app.logger.error(f"Error in /api/nicknames_for_sphere: {e}")
        return jsonify({'message': 'Error fetching nicknames for sphere', 'error': str(e)}), 500

# 管理员登录
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    # 在实际应用中，管理员账号和密码应该更安全地存储和验证
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD_HASH = hashlib.sha256('a0c6ef78064'.encode()).hexdigest() # 预期的密码哈希

    if username == ADMIN_USERNAME and hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
        # 生成管理员JWT token
        admin_token = jwt.encode({
            'admin_user': username,
            'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8) # 管理员token有效期8小时
        }, JWT_SECRET, algorithm='HS256')
        return jsonify({'message': '管理员登录成功', 'token': admin_token}), 200
    else:
        return jsonify({'message': '无效的管理员凭据'}), 401

# 管理员JWT认证装饰器
def admin_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': '管理员Token缺失!'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            if 'admin_user' not in data: # 检查是否为管理员token
                return jsonify({'message': '无效的管理员Token!'}), 401
            # 可以选择将管理员信息传递给路由函数，如果需要的话
            # kwargs['admin_user_data'] = data 
        except jwt.ExpiredSignatureError:
            return jsonify({'message': '管理员Token已过期!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': '无效的管理员Token!'}), 401
        
        return f(*args, **kwargs)
    return decorated

# 获取所有用户列表 (管理员)
@app.route('/admin/users', methods=['GET'])
@admin_token_required
def admin_get_all_users():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int) # 默认每页15条
    offset = (page - 1) * per_page

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 获取总用户数
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()['COUNT(*)']

    # 获取分页用户数据 (已按ID倒序)
    c.execute("""
        SELECT id, email, nickname, age, gender, profession, province, city, created_at, last_online 
        FROM users 
        ORDER BY id DESC 
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    users_rows = c.fetchall()
    conn.close()

    users_list = [dict(user_row) for user_row in users_rows]
    
    return jsonify({
        'users': users_list,
        'total_users': total_users,
        'page': page,
        'per_page': per_page,
        'total_pages': (total_users + per_page - 1) // per_page # 向上取整计算总页数
    }), 200

# 获取单个用户详细信息 (管理员)
@app.route('/admin/users/<int:user_id>', methods=['GET'])
@admin_token_required
def admin_get_user_details(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 获取用户基本信息
    c.execute("""SELECT id, email, nickname, age, gender, profession, province, city, 
                        interests, bio, avatar, created_at, last_online
                 FROM users WHERE id=?""", (user_id,))
    user_data_row = c.fetchone()
    
    if not user_data_row:
        conn.close()
        return jsonify({'message': '用户不存在'}), 404
    
    user_data = dict(user_data_row)
    
    # 获取用户卡片
    c.execute("SELECT id, image_url, order_index FROM user_cards WHERE user_id=? ORDER BY order_index", (user_id,))
    cards_rows = c.fetchall()
    cards = [dict(card_row) for card_row in cards_rows]
    
    conn.close()
    
    profile = {
        'id': user_data['id'],
        'email': user_data['email'],
        'nickname': user_data['nickname'],
        'age': user_data['age'],
        'gender': user_data['gender'],
        'profession': user_data['profession'],
        'province': user_data['province'],
        'city': user_data['city'],
        'interests': user_data['interests'],
        'bio': user_data['bio'],
        'avatar': user_data['avatar'],
        'created_at': user_data['created_at'],
        'last_online': user_data['last_online'],
        'cards': cards
    }
    return jsonify(profile), 200

# 修改用户资料 (管理员)
@app.route('/admin/users/<int:user_id>', methods=['PUT'])
@admin_token_required
def admin_update_user_profile(user_id):
    data = request.json
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    # 检查用户是否存在
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': '用户不存在'}), 404

    fields_to_update = {}
    allowed_fields = ['nickname', 'email', 'age', 'gender', 'profession', 'province', 'city', 'interests', 'bio', 'avatar']
    for field in allowed_fields:
        if field in data:
            fields_to_update[field] = data[field]
    
    if 'password' in data and data['password']: # 如果提供了密码，则更新密码
        fields_to_update['password'] = hashlib.sha256(data['password'].encode()).hexdigest()

    if not fields_to_update and 'cards' not in data:
        conn.close()
        return jsonify({'message': '没有提供可更新的字段'}), 400

    if fields_to_update:
        set_clause = ", ".join([f"{key}=?" for key in fields_to_update.keys()])
        values = list(fields_to_update.values())
        values.append(user_id)
        try:
            c.execute(f"UPDATE users SET {set_clause} WHERE id=?", tuple(values))
        except sqlite3.IntegrityError as e: # 例如 email 重复
            conn.close()
            return jsonify({'message': f'更新失败: {e}'}), 400


    # 更新用户卡片 (如果提供)
    if 'cards' in data:
        # 先删除现有卡片
        c.execute("DELETE FROM user_cards WHERE user_id=?", (user_id,))
        # 插入新卡片
        cards = data.get('cards', [])
        for i, card_url_or_obj in enumerate(cards):
            image_url = card_url_or_obj if isinstance(card_url_or_obj, str) else card_url_or_obj.get('image_url')
            if image_url:
                 c.execute("INSERT INTO user_cards (user_id, image_url, order_index) VALUES (?, ?, ?)",
                      (user_id, image_url, i))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': f'用户 {user_id} 资料更新成功'}), 200

# 删除用户 (管理员)
@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_token_required
def admin_delete_user(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    # 检查用户是否存在
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': '用户不存在'}), 404

    try:
        # 注意：这里仅删除用户表中的用户。
        # 实际应用中，需要考虑如何处理与该用户相关的其他数据，
        # 例如：聊天记录、匹配记录、用户卡片等。
        # 可以选择级联删除（如果数据库支持并设置了外键约束），或者标记为已删除，或者归档。
        # 为简化，此处直接删除用户表记录，其他表中的关联记录将成为孤立数据。
        
        # 1. 删除用户卡片
        c.execute("DELETE FROM user_cards WHERE user_id=?", (user_id,))
        # 2. 删除聊天记录 (作为发送者或接收者)
        c.execute("DELETE FROM chat_messages WHERE sender_id=? OR receiver_id=?", (user_id, user_id))
        # 3. 删除匹配记录
        c.execute("DELETE FROM matches WHERE user_id1=? OR user_id2=?", (user_id, user_id))
        # 4. 删除未读消息记录
        c.execute("DELETE FROM unread_messages WHERE user_id=? OR sender_id=?", (user_id, user_id))
        # 5. 删除用户
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        return jsonify({'message': f'删除用户时发生错误: {e}'}), 500
    finally:
        conn.close()
        
    return jsonify({'message': f'用户 {user_id} 已被删除'}), 200

# 获取用户匹配历史 (管理员)
@app.route('/admin/users/<int:user_id>/matches', methods=['GET'])
@admin_token_required
def admin_get_user_matches(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 检查用户是否存在
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': '用户不存在'}), 404

    # 查询用户的匹配记录
    c.execute("""
        SELECT 
            m.id, 
            m.user_id1, 
            u1.nickname as user1_nickname, 
            m.user_id2, 
            u2.nickname as user2_nickname, 
            m.status, 
            m.created_at
        FROM matches m
        JOIN users u1 ON m.user_id1 = u1.id
        JOIN users u2 ON m.user_id2 = u2.id
        WHERE m.user_id1 = ? OR m.user_id2 = ?
        ORDER BY m.created_at DESC
    """, (user_id, user_id))
    
    matches_rows = c.fetchall()
    conn.close()

    matches_list = [dict(match_row) for match_row in matches_rows]
    
    return jsonify({'matches': matches_list}), 200

# 获取用户聊天会话列表 (管理员)
@app.route('/admin/users/<int:user_id>/chat_partners', methods=['GET'])
@admin_token_required
def admin_get_user_chat_partners(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 检查用户是否存在
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': '用户不存在'}), 404

    # 查询与该用户有过私聊的用户列表及最新一条消息
    c.execute("""
        SELECT 
            p.partner_id,
            u.nickname as partner_nickname,
            u.avatar as partner_avatar,
            (SELECT message FROM chat_messages 
             WHERE ((sender_id = :user_id AND receiver_id = p.partner_id) OR (sender_id = p.partner_id AND receiver_id = :user_id))
                   AND room_id IS NULL
             ORDER BY created_at DESC LIMIT 1) as last_message,
            (SELECT created_at FROM chat_messages 
             WHERE ((sender_id = :user_id AND receiver_id = p.partner_id) OR (sender_id = p.partner_id AND receiver_id = :user_id))
                   AND room_id IS NULL
             ORDER BY created_at DESC LIMIT 1) as last_message_time,
            (SELECT sender_id FROM chat_messages 
             WHERE ((sender_id = :user_id AND receiver_id = p.partner_id) OR (sender_id = p.partner_id AND receiver_id = :user_id))
                   AND room_id IS NULL
             ORDER BY created_at DESC LIMIT 1) as last_message_sender_id
        FROM (
            SELECT DISTINCT 
                CASE WHEN sender_id = :user_id THEN receiver_id ELSE sender_id END as partner_id
            FROM chat_messages
            WHERE (sender_id = :user_id OR receiver_id = :user_id) AND room_id IS NULL
        ) p
        JOIN users u ON u.id = p.partner_id
        ORDER BY last_message_time DESC
    """, {'user_id': user_id})
    
    partners_rows = c.fetchall()
    conn.close()
    
    partners_list = [dict(row) for row in partners_rows]
    return jsonify({'chat_partners': partners_list}), 200

# 获取指定两个用户之间的聊天记录 (管理员)
@app.route('/admin/chats', methods=['GET'])
@admin_token_required
def admin_get_specific_chat_history():
    user_id1 = request.args.get('user_id1', type=int)
    user_id2 = request.args.get('user_id2', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 50 # 和前端保持一致或可配置
    offset = (page - 1) * per_page

    if not user_id1 or not user_id2:
        return jsonify({'message': '必须提供 user_id1 和 user_id2'}), 400
    
    if user_id1 == user_id2:
        return jsonify({'message': 'user_id1 和 user_id2 不能相同'}), 400

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 检查用户是否存在
    c.execute("SELECT id FROM users WHERE id=?", (user_id1,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': f'用户 {user_id1} 不存在'}), 404
    c.execute("SELECT id FROM users WHERE id=?", (user_id2,))
    if not c.fetchone():
        conn.close()
        return jsonify({'message': f'用户 {user_id2} 不存在'}), 404

    c.execute("""
        SELECT cm.id, cm.sender_id, u_sender.nickname as sender_nickname, 
               cm.receiver_id, u_receiver.nickname as receiver_nickname, 
               cm.message, cm.message_type, cm.created_at
        FROM chat_messages cm
        JOIN users u_sender ON cm.sender_id = u_sender.id
        JOIN users u_receiver ON cm.receiver_id = u_receiver.id
        WHERE ((cm.sender_id = ? AND cm.receiver_id = ?) OR (cm.sender_id = ? AND cm.receiver_id = ?))
              AND cm.room_id IS NULL
        ORDER BY cm.created_at DESC
        LIMIT ? OFFSET ?
    """, (user_id1, user_id2, user_id2, user_id1, per_page, offset))
    
    messages_rows = c.fetchall()
    conn.close()

    messages_list = [dict(msg_row) for msg_row in messages_rows]
    messages_list.reverse() #  最新的在最后
    
    return jsonify({'chat_history': messages_list}), 200


# 发送私聊消息
@app.route('/api/send-message', methods=['POST'])
@token_required
def send_message(current_user_id):
    data = request.json
    receiver_id = data.get('receiver_id')
    message = data.get('message')
    
    if not receiver_id or not message:
        return jsonify({'message': '接收者ID和消息内容不能为空'}), 400
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    # 插入消息记录
    c.execute("""INSERT INTO chat_messages (sender_id, receiver_id, message) 
                 VALUES (?, ?, ?)""",
              (current_user_id, receiver_id, message))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': '消息发送成功'}), 200

# 简单调试接口（无需认证）
@app.route("/api/debug/simple", methods=["GET"])
def simple_debug():
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # 获取基本统计
        c.execute("SELECT COUNT(*) as total FROM users")
        total_users = c.fetchone()["total"]
        
        c.execute("SELECT COUNT(*) as non_robots FROM users WHERE is_robot = 0 OR is_robot IS NULL")
        non_robot_users = c.fetchone()["non_robots"]
        
        c.execute("SELECT COUNT(*) as with_nickname FROM users WHERE nickname IS NOT NULL AND nickname != '' AND (is_robot = 0 OR is_robot IS NULL)")
        users_with_nickname = c.fetchone()["with_nickname"]
        
        # 获取前3个用户示例 (保留原有的简单示例)
        c.execute("SELECT id, nickname, is_robot FROM users LIMIT 3")
        simple_sample_users = [dict(row) for row in c.fetchall()]

        # 新增：获取前10个用户及其主卡片信息
        c.execute("""
            SELECT 
                u.id, 
                u.nickname, 
                u.is_robot,
                u.avatar,
                (SELECT uc.image_url FROM user_cards uc WHERE uc.user_id = u.id ORDER BY uc.order_index LIMIT 1) as main_card
            FROM users u
            ORDER BY u.id 
            LIMIT 10
        """)
        detailed_sample_users_with_cards = [dict(row) for row in c.fetchall()]
        
        # 获取未读消息总数
        c.execute("SELECT COUNT(*) as total_unread FROM unread_messages")
        total_unread_count = c.fetchone()["total_unread"] # Renamed to avoid conflict

        # 获取 unread_messages 表的详细内容
        c.execute("SELECT id, user_id, sender_id, message_id, created_at FROM unread_messages ORDER BY user_id, sender_id, created_at DESC")
        unread_rows_details = c.fetchall()
        unread_list_details = [dict(row) for row in unread_rows_details]
        
        conn.close()
        
        return jsonify({
            "status": "success",
            "database_stats": {
                "total_users": total_users,
                "non_robot_users": non_robot_users,
                "users_with_nickname": users_with_nickname,
                "total_unread_messages_count": total_unread_count # Use renamed variable
            },
            "simple_sample_users": simple_sample_users, # Renamed original sample
            "detailed_sample_top10_users_with_cards": detailed_sample_users_with_cards, # Added new detailed sample
            "unread_messages_details": { # Add detailed unread messages
                "count": len(unread_list_details),
                "data": unread_list_details
            }
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error in /api/debug/simple: {e}")
        return jsonify({
            "status": "error",
            "error_message": str(e)
        }), 500

# 原 /api/debug/unread-messages 接口已合并到 /api/debug/simple 中，此处删除

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host=config.HTTP_HOST, port=config.HTTP_PORT)
