import os
from google import genai
from google.genai import types

# --- 1. 代理配置 (对应你的 7897 端口) ---
os.environ["http_proxy"] = "http://127.0.0.1:7897"
os.environ["https_proxy"] = "http://127.0.0.1:7897"

# --- 2. 初始化 Client ---
# 请确保填写你从 Google AI Studio 获取的 API KEY
client = genai.Client(
    api_key="AIzaSyAE8HLnkxCgdrVXSrZ-TonsHhFlwlOkJjg",
    http_options={'api_version': 'v1beta'} 
)

def generate_gemini_md():
    print("🔍 正在扫描 hydros-python-sdk 目录结构...")
    
    # 获取项目根目录 (假设脚本在 examples 文件夹下，我们向上跳一级)
    root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    exclude = {'.git', '.vscode', '__pycache__', 'venv', 'node_modules', '.gemini', '.claude'}
    path_info = []
    
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in exclude]
        # 计算相对路径深度
        rel_path = os.path.relpath(root, root_path)
        if rel_path == ".":
            level = 0
            display_name = os.path.basename(root_path)
        else:
            level = rel_path.count(os.sep) + 1
            display_name = os.path.basename(root)
            
        indent = '  ' * level
        path_info.append(f"{indent}📁 {display_name}/")
        
        # 每个文件夹列出部分文件
        for f in files[:8]:
            path_info.append(f"{indent}  - {f}")

    structure_context = "\n".join(path_info[:200])

    # --- 3. 定义 Prompt ---
    # 刚才报错就是因为漏掉了这一行定义
    prompt_text = f"""
    你是一个专业的软件文档工程师。请分析以下 hydros-python-sdk 项目的目录结构，并生成一个全面的 GEMINI.md 文件。
    
    项目目录结构:
    {structure_context}

    生成的 GEMINI.md 必须包含：
    1. # Project Overview: 简述这是一个基于 Python 的水利/水务智能体(Agent) SDK。
    2. # Key Components: 说明 hydros_agent_sdk 核心包的作用。
    3. # Setup & Usage: 建议安装和运行方式。
    4. # Architecture: 简述其智能体化的架构特点。

    请直接输出 Markdown 内容，无需额外解释。
    """

    print("🚀 正在通过 google.genai 调用 Gemini 1.5 Flash...")
    try:
        # 尝试生成内容
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt_text
        )
        
        # --- 4. 写入文件到项目根目录 ---
        output_file = os.path.join(root_path, "GEMINI.md")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(response.text)
            
        print("-" * 30)
        print(f"✅ 成功！GEMINI.md 已生成在: {output_file}")
        
    except Exception as e:
        print(f"❌ 调用失败: {e}")

if __name__ == "__main__":
    generate_gemini_md()