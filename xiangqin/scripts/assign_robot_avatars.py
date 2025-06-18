import sqlite3
import os
import random

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'backend', 'users.db')
AVATARS_BASE_PATH = os.path.join(BASE_DIR, 'frontend', 'images', 'avatars')
MALE_AVATARS_PATH = os.path.join(AVATARS_BASE_PATH, 'male')
FEMALE_AVATARS_PATH = os.path.join(AVATARS_BASE_PATH, 'female')

def get_random_avatar(gender):
    """根据性别从指定目录随机获取一个头像路径"""
    avatar_dir = MALE_AVATARS_PATH if gender == 'male' else FEMALE_AVATARS_PATH
    
    if not os.path.exists(avatar_dir):
        print(f"错误：头像目录不存在 {avatar_dir}")
        return None
        
    avatars = [f for f in os.listdir(avatar_dir) if os.path.isfile(os.path.join(avatar_dir, f))]
    if not avatars:
        print(f"错误：头像目录为空 {avatar_dir}")
        return None
    
    chosen_avatar_name = random.choice(avatars)
    # 返回以 / 开头的、相对于服务器根的路径
    relative_path = os.path.join('frontend', 'images', 'avatars', gender, chosen_avatar_name).replace('\\', '/')
    return f"/{relative_path}"

def update_robot_avatars():
    """更新所有机器人的头像"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 获取所有机器人用户 (id 和 gender)
        c.execute("SELECT id, gender FROM users WHERE is_robot = 1")
        robots = c.fetchall()

        if not robots:
            print("数据库中没有找到机器人用户。")
            return

        updated_count = 0
        for robot_id, gender in robots:
            new_avatar_path = get_random_avatar(gender)
            if new_avatar_path:
                try:
                    # 更新 users 表中的头像
                    c.execute("UPDATE users SET avatar = ? WHERE id = ?", (new_avatar_path, robot_id))
                    
                    # 更新 user_cards 表中的主卡片头像 (order_index = 0)
                    # 假设每个机器人都有一个 order_index = 0 的主卡片
                    c.execute("UPDATE user_cards SET image_url = ? WHERE user_id = ? AND order_index = 0", 
                              (new_avatar_path, robot_id))
                    
                    conn.commit()
                    print(f"机器人 ID {robot_id} ({gender}) 的头像已更新为: {new_avatar_path}")
                    updated_count += 1
                except sqlite3.Error as e:
                    print(f"更新机器人 ID {robot_id} 头像时发生数据库错误: {e}")
                    if conn:
                        conn.rollback() # 回滚当前事务的更改
            else:
                print(f"未能为机器人 ID {robot_id} ({gender}) 获取头像。")

        print(f"\n总共更新了 {updated_count} 个机器人的头像。")

    except sqlite3.Error as e:
        print(f"连接数据库或执行查询时发生错误: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # 确保头像目录存在
    if not os.path.exists(MALE_AVATARS_PATH) or not os.path.exists(FEMALE_AVATARS_PATH):
        print("错误：男性或女性头像目录不存在。请检查路径：")
        print(f"男性头像目录: {MALE_AVATARS_PATH}")
        print(f"女性头像目录: {FEMALE_AVATARS_PATH}")
        print("请确保这些目录存在并且包含图片文件。")
    else:
        print(f"使用数据库: {DB_PATH}")
        print(f"男性头像源目录: {MALE_AVATARS_PATH}")
        print(f"女性头像源目录: {FEMALE_AVATARS_PATH}")
        update_robot_avatars()
    print("机器人头像分配脚本执行完毕。")
