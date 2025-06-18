import os

# 创建头像和背景图片目录
os.makedirs('frontend/images/avatars/male', exist_ok=True)
os.makedirs('frontend/images/avatars/female', exist_ok=True) 
os.makedirs('frontend/images/backgrounds/male', exist_ok=True)
os.makedirs('frontend/images/backgrounds/female', exist_ok=True)

print("图片目录结构创建完成")
