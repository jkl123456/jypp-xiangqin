import sqlite3
import os
import random

# 连接数据库
conn = sqlite3.connect('/www/wwwroot/xiangqin/backend/users.db')
cursor = conn.cursor()

# 获取图片文件列表
male_avatars = os.listdir('frontend/images/avatars/male')
female_avatars = os.listdir('frontend/images/avatars/female')
male_backgrounds = os.listdir('frontend/images/backgrounds/male')
female_backgrounds = os.listdir('frontend/images/backgrounds/female')

# 更新男性用户
cursor.execute("SELECT id FROM users WHERE gender='male'")
male_users = cursor.fetchall()
for user_id in male_users:
    avatar = random.choice(male_avatars)
    background = random.choice(male_backgrounds)
    cursor.execute("""
        UPDATE users 
        SET avatar=?, background=?
        WHERE id=?
    """, (f"images/avatars/male/{avatar}", f"images/backgrounds/male/{background}", user_id[0]))

# 更新女性用户
cursor.execute("SELECT id FROM users WHERE gender='female'")
female_users = cursor.fetchall()
for user_id in female_users:
    avatar = random.choice(female_avatars)
    background = random.choice(female_backgrounds)
    cursor.execute("""
        UPDATE users 
        SET avatar=?, background=?
        WHERE id=?
    """, (f"images/avatars/female/{avatar}", f"images/backgrounds/female/{background}", user_id[0]))

conn.commit()
conn.close()

print("用户头像和背景图片更新完成")
