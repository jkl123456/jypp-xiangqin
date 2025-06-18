import sqlite3
import os

DATABASE_PATH = '/www/wwwroot/xiangqin/backend/users.db'
# For local testing, you might want to use a relative path if the script is run from the project root
# Example: DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'backend', 'users.db')

def is_base64_image_data(url_string):
    """Checks if a string looks like a Base64 image data URL."""
    if not isinstance(url_string, str):
        return False
    return url_string.startswith('data:image/') and ';base64,' in url_string

def clean_base64_from_users_avatar():
    """Cleans Base64 data from the avatar column in the users table."""
    conn = None
    updated_count = 0
    try:
        print(f"Connecting to database: {DATABASE_PATH}")
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT id, avatar FROM users WHERE avatar IS NOT NULL AND avatar != ''")
        users_with_avatars = cursor.fetchall()
        
        print(f"Found {len(users_with_avatars)} users with avatar data to check.")

        for user_id, avatar_url in users_with_avatars:
            if is_base64_image_data(avatar_url):
                print(f"User ID {user_id}: Avatar is Base64. Clearing.")
                cursor.execute("UPDATE users SET avatar = NULL WHERE id = ?", (user_id,))
                updated_count += 1
        
        conn.commit()
        print(f"Cleaned Base64 avatars for {updated_count} users.")

    except sqlite3.Error as e:
        print(f"SQLite error during users avatar cleaning: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during users avatar cleaning: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed for users avatar cleaning.")
    return updated_count

def clean_base64_from_user_cards():
    """Cleans Base64 data from the image_url column in the user_cards table."""
    conn = None
    updated_count = 0
    try:
        print(f"Connecting to database: {DATABASE_PATH}")
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT id, image_url FROM user_cards WHERE image_url IS NOT NULL AND image_url != ''")
        cards_with_urls = cursor.fetchall()

        print(f"Found {len(cards_with_urls)} user cards with image_url data to check.")

        for card_id, image_url in cards_with_urls:
            if is_base64_image_data(image_url):
                print(f"Card ID {card_id}: image_url is Base64. Clearing.")
                # Alternatively, you might want to delete the row if the card is unusable without a valid URL
                # For now, just clearing the URL.
                cursor.execute("UPDATE user_cards SET image_url = NULL WHERE id = ?", (card_id,))
                updated_count += 1
        
        conn.commit()
        print(f"Cleaned Base64 image_urls for {updated_count} user cards.")

    except sqlite3.Error as e:
        print(f"SQLite error during user_cards cleaning: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during user_cards cleaning: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed for user_cards cleaning.")
    return updated_count

if __name__ == '__main__':
    print("Starting database cleanup for Base64 image data...")
    
    # Important: Backup your database before running this script!
    # proceed = input("Have you backed up your database? (yes/no): ")
    # if proceed.lower() != 'yes':
    #     print("Cleanup aborted. Please backup your database first.")
    #     exit()

    print("\n--- Cleaning users table (avatar column) ---")
    users_cleaned = clean_base64_from_users_avatar()
    
    print("\n--- Cleaning user_cards table (image_url column) ---")
    cards_cleaned = clean_base64_from_user_cards()
    
    print("\n--- Cleanup Summary ---")
    print(f"Total users whose avatars were cleared: {users_cleaned}")
    print(f"Total user cards whose image_urls were cleared: {cards_cleaned}")
    print("Database cleanup finished.")
    print("Remember to restart your backend server if it was running during the cleanup.")
