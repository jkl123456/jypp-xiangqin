import os
import requests

# 男性默认图片URL
MALE_AVATAR_URL = "https://via.placeholder.com/300x300/4682B4/FFFFFF?text=Male+Avatar"
MALE_BG_URL = "https://via.placeholder.com/1200x600/1E90FF/FFFFFF?text=Male+Background"

# 女性默认图片URL  
FEMALE_AVATAR_URL = "https://via.placeholder.com/300x300/FF69B4/FFFFFF?text=Female+Avatar"
FEMALE_BG_URL = "https://via.placeholder.com/1200x600/FFB6C1/FFFFFF?text=Female+Background"

def download_image(url, save_path):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)

# 下载男性图片
download_image(MALE_AVATAR_URL, "frontend/images/avatars/male/default.jpg")
download_image(MALE_BG_URL, "frontend/images/backgrounds/male/default.jpg")

# 下载女性图片
download_image(FEMALE_AVATAR_URL, "frontend/images/avatars/female/default.jpg") 
download_image(FEMALE_BG_URL, "frontend/images/backgrounds/female/default.jpg")

print("默认图片下载完成")
