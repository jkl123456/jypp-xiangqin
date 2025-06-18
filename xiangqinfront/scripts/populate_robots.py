import sqlite3
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'backend', 'users.db')

def add_is_robot_column():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_robot INTEGER DEFAULT 0")
        print("Column 'is_robot' added to 'users' table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column 'is_robot' already exists in 'users' table.")
        else:
            print(f"Error adding column 'is_robot': {e}")
            raise
    finally:
        conn.commit()
        conn.close()

def generate_robots():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 检查是否已有机器人，避免重复插入
    c.execute("SELECT COUNT(*) FROM users WHERE is_robot = 1")
    robot_count = c.fetchone()[0]
    if robot_count >= 30:
        print(f"{robot_count} robots already exist. No new robots will be added.")
        conn.close()
        return

    # 机器人基本信息
    # 15 male, 15 female
    male_nicknames = [
        "温柔骑士", "守护星辰", "晨曦暖阳", "智慧引路人", "幽默绅士",
        "梦想家小张", "代码诗人李", "星空旅者王", "音乐爱好者赵", "运动健将孙",
        "深夜食堂老板", "故事大王小刘", "治愈系暖男吴", "思考者小钱", "探索家小周"
    ]
    female_nicknames = [
        "月光女神", "甜心宝贝", "彩虹仙子", "知心姐姐", "文艺少女",
        "花语者小陈", "美食家小杨", "旅行规划师黄", "艺术爱好者徐", "宠物达人胡",
        "心灵捕手小林", "时尚顾问小马", "瑜伽导师小高", "烘焙甜心小罗", "梦想编织者小郭"
    ]

    robots_to_add = []
    # 密码hash (使用 "robotpassword" 作为示例)
    password_hash = hashlib.sha256("robotpassword".encode()).hexdigest()
    default_avatar_male = "frontend/assets/images/robot_male_avatar.png" # 假设有此路径
    default_avatar_female = "frontend/assets/images/robot_female_avatar.png" # 假设有此路径
    default_city = "赛博城"
    default_province = "硅基省"

    # 生成男性机器人
    for i in range(15):
        if robot_count + len(robots_to_add) >= 30: break
        email = f"male_robot_{i+1}@bot.local"
        nickname = male_nicknames[i % len(male_nicknames)]
        # 确保昵称不重复（简单处理，如果昵称列表本身不重复则大部分情况OK）
        c.execute("SELECT id FROM users WHERE nickname = ?", (nickname,))
        if c.fetchone():
            nickname = f"{nickname}_{i+1}"

        robots_to_add.append((
            email, password_hash, nickname, 'male', default_city, default_province, default_avatar_male, 1
        ))

    # 生成女性机器人
    for i in range(15):
        if robot_count + len(robots_to_add) >= 30: break
        email = f"female_robot_{i+1}@bot.local"
        nickname = female_nicknames[i % len(female_nicknames)]
        c.execute("SELECT id FROM users WHERE nickname = ?", (nickname,))
        if c.fetchone():
            nickname = f"{nickname}_{i+1}"
        
        robots_to_add.append((
            email, password_hash, nickname, 'female', default_city, default_province, default_avatar_female, 1
        ))
    
    if robots_to_add:
        try:
            # 先插入用户基本信息
            user_insert_query = """
                INSERT INTO users (email, password, nickname, gender, city, province, avatar, is_robot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            c.executemany(user_insert_query, robots_to_add)
            conn.commit()
            print(f"Successfully added basic info for {len(robots_to_add)} robots to the users table.")

            # 为每个成功插入的机器人添加主卡片
            # 需要获取刚插入的机器人的 ID 和头像信息
            # robots_to_add 中的顺序与插入顺序一致，但获取 lastrowid 对 executemany 不直接适用
            # 因此，我们将根据 email 查询这些机器人的 ID

            robot_cards_to_add = []
            for robot_data in robots_to_add:
                email = robot_data[0] # email 是唯一的
                avatar_url = robot_data[6] # avatar url
                c.execute("SELECT id FROM users WHERE email = ?", (email,))
                user_row = c.fetchone()
                if user_row:
                    user_id = user_row[0]
                    # 使用头像作为主卡片，order_index 为 0
                    robot_cards_to_add.append((user_id, avatar_url, 0))
                else:
                    print(f"Could not find user_id for robot with email {email} after insert.")
            
            if robot_cards_to_add:
                card_insert_query = """
                    INSERT INTO user_cards (user_id, image_url, order_index)
                    VALUES (?, ?, ?)
                """
                c.executemany(card_insert_query, robot_cards_to_add)
                conn.commit()
                print(f"Successfully added main cards for {len(robot_cards_to_add)} robots to the user_cards table.")

        except sqlite3.IntegrityError as e:
            print(f"Error inserting robots (possibly due to unique email constraint): {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    
    conn.close()

if __name__ == "__main__":
    # 确保 backend 目录存在，如果脚本是从 scripts 目录运行
    backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
    if not os.path.exists(backend_dir):
        os.makedirs(backend_dir)
        print(f"Created directory: {backend_dir}")

    # 确保数据库文件存在，如果不存在则 http_server.py 的 init_db 会创建
    # 但这里我们至少需要它存在才能连接
    if not os.path.exists(DB_PATH):
        print(f"Database file not found at {DB_PATH}. Please ensure the main server has run once to initialize the DB.")
        # 尝试调用 init_db (如果可以导入) 或提示用户先运行主服务
        # For simplicity, we'll assume init_db from http_server should be run first by the user.
        # from backend.http_server import init_db # This might cause circular or path issues
        # init_db()
        # print("Attempted to initialize database.")
    else:
        add_is_robot_column()
        generate_robots()

    print("Robot population script finished.")
