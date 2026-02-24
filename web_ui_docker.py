import os
# 物理级免疫系统代理，防止本地流量被 VPN 劫持
os.environ["no_proxy"] = "localhost, 127.0.0.1, ::1"
os.environ["NO_PROXY"] = "localhost, 127.0.0.1, ::1"

import gradio as gr
from openai import OpenAI
import re
import subprocess
import time

# ================= 1. 核心网络与记忆配置 =================
AUTODL_API_BASE = "http://127.0.0.1:8000/v1"
client = OpenAI(api_key="EMPTY", base_url=AUTODL_API_BASE)

# 全局上下文记忆（初始只包含系统提示词）
messages_history = [
    {"role": "system",
     "content": "你是一个顶级Python工程师。只输出完整且可运行的Python代码，用```python和```包裹。不要废话，不要解释。"}
]


# ================= 2. 基础功能函数 =================
def extract_code(text):
    match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
    return match.group(1) if match else None


def run_code(code_str):
    # 1. 建立专属的“隔离区”文件夹，防止污染主项目
    workspace_dir = os.path.abspath("workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    file_path = os.path.join(workspace_dir, "generated_sandbox.py")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code_str)

    # 2. 组装坚不可摧的 Docker 启动命令
    # --rm: 运行结束立刻骨灰级销毁容器
    # --network none: 物理断网，防止 AI 写恶意爬虫
    # -m 256m: 限制最多使用 256MB 内存，防死循环撑爆电脑
    # -v: 把本地的 workspace 挂载到容器的 /app 目录
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "-m", "256m",
        "-v", f"{workspace_dir}:/app",
        "-w", "/app",
        "python:3.10-slim",
        "python", "generated_sandbox.py"
    ]

    try:
        # 设置 15 秒超时，防止代码死循环卡死系统
        result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return False, result.stderr
        return True, result.stdout
    except subprocess.TimeoutExpired:
        return False, "⚠️ 执行超时！大模型生成的代码引发了死循环或执行时间过长，已被沙箱强制中止。"
    except Exception as e:
        return False, f"沙箱启动发生严重异常: {str(e)}"


# ================= 3. 中枢逻辑：处理用户输入与自我修复 =================
def process_input(user_input, chatbot_history):
    if not user_input.strip():
        yield "", chatbot_history, "", "⚠️ 请输入你的需求"
        return

    # 第一步：UI界面先显示用户的提问，机器人状态改为“思考中”
    chatbot_history.append([user_input, "🧠 正在连接 Qwen 大脑进行推理..."])
    yield "", chatbot_history, "", "⏳ 正在生成代码..."

    # 把用户需求压入全局记忆
    messages_history.append({"role": "user", "content": user_input})

    # 开启最多 3 次的 Vibe Coding 自我修复循环
    for attempt in range(1, 4):
        # 1. 呼叫大模型
        response = client.chat.completions.create(
            model="qwen2.5-coder",
            messages=messages_history,
            temperature=0.1
        )
        assistant_reply = response.choices[0].message.content
        messages_history.append({"role": "assistant", "content": assistant_reply})

        # 2. 解析代码
        code = extract_code(assistant_reply)
        if not code:
            messages_history.append({"role": "user", "content": "未检测到```python代码块，请重新严格按格式输出。"})
            chatbot_history[-1][1] = f"❌ 第 {attempt} 次生成未提取到规范代码，命令模型重试中..."
            yield "", chatbot_history, "", "⚠️ 格式错误，重试中..."
            continue

        # 3. 在本地沙箱运行代码
        chatbot_history[-1][1] = f"⚙️ 第 {attempt} 次代码生成完毕，正在本地沙箱执行..."
        yield "", chatbot_history, code, "🏃 代码运行中..."

        success, output = run_code(code)

        # 4. 判断结果并闭环
        if success:
            messages_history.append(
                {"role": "user", "content": f"代码执行成功！这是终端输出：\n{output}\n请保持状态，等待下个指令。"})
            chatbot_history[-1][1] = f"✅ 执行成功！系统已完成任务。"
            yield "", chatbot_history, code, output
            return  # 成功后直接结束本次请求
        else:
            messages_history.append(
                {"role": "user", "content": f"你写的代码执行报错。错误日志：\n{output}\n请分析并输出修复后的完整代码。"})
            chatbot_history[-1][1] = f"⚠️ 第 {attempt} 次执行报错，模型正在根据报错日志进行自我修复..."
            yield "", chatbot_history, code, f"❌ 运行报错：\n{output}"
            time.sleep(1)  # 稍微停顿一下UI，让用户能看清重试过程

    # 如果3次全失败
    chatbot_history[-1][1] = "💀 经过 3 次尝试，模型依然未能修复 Bug。"
    yield "", chatbot_history, code, "💀 任务宣告失败，请考虑拆分需求或提供更具体的思路。"


def clear_history():
    # 清空记忆，恢复出厂设置
    global messages_history
    messages_history = [{"role": "system",
                         "content": "你是一个顶级Python工程师。只输出完整且可运行的Python代码，用```python和```包裹。不要废话，不要解释。"}]
    return [], "", ""


# ================= 4. 前端网页布局 (Gradio Blocks) =================
with gr.Blocks(title="VibeCoder 智能引擎", theme=gr.themes.Monochrome()) as demo:
    gr.Markdown(
        "# 🚀 VibeCoder: 全栈意念编程引擎\n**架构**：本地 Client (展示与沙箱) + 云端 Server (Qwen2.5-Coder-7B 推理)")

    with gr.Row():
        # 左侧区域：交互聊天
        with gr.Column(scale=5):
            chatbot = gr.Chatbot(label="Agent 思维链路", height=600)
            msg = gr.Textbox(label="👨‍💻 输入你的需求 (按下 Enter 发送)",
                             placeholder="例如：写一个自动爬取某网站标题的脚本...")
            clear = gr.Button("🗑️ 清除历史记忆，开启新会话")

        # 右侧区域：代码与沙箱输出
        with gr.Column(scale=5):
            code_display = gr.Code(label="💻 最新生成代码", language="python", interactive=False)
            terminal_output = gr.Textbox(label="🖥️ 终端输出面板 (沙箱反馈)", lines=15, interactive=False)

    # 绑定组件与事件
    msg.submit(process_input, inputs=[msg, chatbot], outputs=[msg, chatbot, code_display, terminal_output])
    clear.click(clear_history, inputs=None, outputs=[chatbot, code_display, terminal_output])

# ================= 5. 启动服务 =================
if __name__ == "__main__":
    print("🌐 正在启动 VibeCoder Web 服务...")
    # server_name="127.0.0.1" 确保仅本地可见，避免安全风险
    demo.launch(server_name="127.0.0.1", server_port=7860, share=True)