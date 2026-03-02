import shutil
import os

def cleanup():
    print("--- Starting Release Cleanup ---")
    
    # 1. 移除临时虚拟环境 (如果有)
    if os.path.exists("s3-team-share/.venv"):
        shutil.rmtree("s3-team-share/.venv")
        print("Removed .venv")

    # 2. 移除 site-packages (这些是重头戏，让 start.bat 在对方电脑上重新下)
    site_packages = "s3-team-share/python_win/Lib/site-packages"
    if os.path.exists(site_packages):
        # 我们保留 pip，删除其他的
        for item in os.listdir(site_packages):
            item_path = os.path.join(site_packages, item)
            if "pip" not in item.lower() and "setuptools" not in item.lower():
                try:
                    if os.path.isdir(item_path): shutil.rmtree(item_path)
                    else: os.remove(item_path)
                except: pass
        print("Cleaned site-packages (kept pip only)")

    # 3. 递归删除所有 pycache
    for root, dirs, files in os.walk("s3-team-share"):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root, "__pycache__"))
            
    print("--- Cleanup Done! ---")
    print("Now you can ZIP the 's3-team-share' folder.")

if __name__ == "__main__":
    cleanup()
