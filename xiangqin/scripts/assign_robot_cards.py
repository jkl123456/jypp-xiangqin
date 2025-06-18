import sqlite3
import os

# --- 配置 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # 项目根目录 (e:/auto/xiangqin8/xiangqin)
DB_PATH = os.path.join(BASE_DIR, 'backend', 'users.db')
IMAGE_BASE_DIR_FRONTEND = os.path.join(BASE_DIR, 'frontend', 'images', 'backgrounds')
IMAGE_URL_PREFIX = 'images/backgrounds' # 前端访问图片的相对路径前缀

def get_image_paths_for_gender(gender):
    """根据性别获取背景图片文件夹中的图片相对路径列表"""
    gender_folder = 'male' if gender == 'male' else 'female'
    specific_image_dir = os.path.join(IMAGE_BASE_DIR_FRONTEND, gender_folder)
    
    image_files = []
    if os.path.exists(specific_image_dir) and os.path.isdir(specific_image_dir):
        for filename in os.listdir(specific_image_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                # 存储相对于 frontend 目录的路径，供前端使用
                image_files.append(f"{IMAGE_URL_PREFIX}/{gender_folder}/{filename}")
    else:
        print(f"警告: 目录 {specific_image_dir} 不存在或不是一个目录。")
    return image_files

def assign_cards_to_robots():
    """为所有机器人用户分配背景图片作为主卡片"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 1. 获取所有机器人用户 (id, gender)
        c.execute("SELECT id, gender FROM users WHERE is_robot = 1")
        robots = c.fetchall()

        if not robots:
            print("数据库中没有找到机器人用户。")
            return

        print(f"找到了 {len(robots)} 个机器人用户。")

        # 2. 获取男性和女性背景图片列表
        male_background_images = get_image_paths_for_gender('male')
        female_background_images = get_image_paths_for_gender('female')

        if not male_background_images and not female_background_images:
            print("警告: 未在 'frontend/images/backgrounds/male' 或 'frontend/images/backgrounds/female' 目录下找到任何图片。")
            # 即使没有背景图，也尝试清除旧卡片
        elif not male_background_images:
            print("警告: 未在 'frontend/images/backgrounds/male' 目录下找到任何男性背景图片。")
        elif not female_background_images:
            print("警告: 未在 'frontend/images/backgrounds/female' 目录下找到任何女性背景图片。")


        updated_robots_count = 0
        for robot_id, gender in robots:
            image_to_assign = None
            image_list_for_gender = []

            if gender == 'male':
                image_list_for_gender = male_background_images
            elif gender == 'female':
                image_list_for_gender = female_background_images
            else:
                print(f"机器人 ID: {robot_id} 性别未知 ('{gender}')，将尝试使用男性图片（如果可用）。")
                image_list_for_gender = male_background_images # 默认或混合逻辑

            if not image_list_for_gender:
                print(f"机器人 ID: {robot_id} (性别: {gender}) 没有可用的背景图片列表。跳过卡片分配。")
                # 仍然尝试清除旧卡片
                c.execute("DELETE FROM user_cards WHERE user_id = ?", (robot_id,))
                conn.commit() # 提交删除操作
                continue

            # 循环使用图片列表中的图片
            # 使用 (robot_id - 1) % len确保即使id不从1开始也能较好地分布
            # 如果列表为空，这里会出错，但前面已经处理了
            image_to_assign = image_list_for_gender[(robot_id -1 ) % len(image_list_for_gender)]

            # 3. 清除该机器人已有的所有卡片记录
            c.execute("DELETE FROM user_cards WHERE user_id = ?", (robot_id,))
            
            # 4. 插入新的主卡片记录 (order_index = 0)
            if image_to_assign:
                try:
                    c.execute("INSERT INTO user_cards (user_id, image_url, order_index) VALUES (?, ?, ?)",
                              (robot_id, image_to_assign, 0))
                    print(f"为机器人 ID: {robot_id} (性别: {gender}) 分配了主卡片: {image_to_assign}")
                    updated_robots_count += 1
                except sqlite3.Error as e:
                    print(f"错误: 无法为机器人 ID: {robot_id} 插入卡片 {image_to_assign}。错误: {e}")
            else:
                print(f"警告: 机器人 ID: {robot_id} (性别: {gender}) 最终没有可分配的图片。")


        conn.commit()
        print(f"\n成功为 {updated_robots_count} 个机器人更新/分配了主卡片。")

    except sqlite3.Error as e:
        print(f"数据库操作发生错误: {e}")
    except Exception as e:
        print(f"发生意外错误: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("开始为机器人分配背景图片作为主卡片...")
    assign_cards_to_robots()
    print("脚本执行完毕。")
