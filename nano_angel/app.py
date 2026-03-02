import streamlit as st

st.set_page_config(page_title="Nano Camera Angle Prompter", page_icon="🍌", layout="centered")

st.title("🍌 Nano Banana Camera Angle Prompter")
st.markdown("""
这个工具可以帮你生成高质量的 Prompt，用于 ComfyUI 中的 **Gemini Nano Banana 2** 节点。
核心目标是：**仅改变镜头的拍摄角度，而严格保持原图中的人物特征、服装、背景、光影和画风完全不变。**
""")

st.header("1. 设定镜头运动")
st.markdown("描述你希望摄像机如何移动或最终处于什么位置。")
angle_input = st.text_input(
    "例如：向左旋转60度 / 变为正侧面轮廓 / 俯视视角",
    placeholder="e.g., The camera rotates 60 degrees to the left, capturing a profile view."
)

st.header("2. 描述画面主体 (可选但强烈建议)")
st.markdown("简单描述一下原图里有什么（这能帮助模型更好地锚定需要保留的元素）。")
subject_input = st.text_area(
    "例如：一个穿着白色衬衫的黑发男子，背景是赛博朋克城市。",
    placeholder="e.g., A young man with black hair wearing a white shirt standing in a neon-lit futuristic city."
)

st.header("3. 额外强调细节 (可选)")
st.markdown("如果有绝对不能变的特殊细节，可以在这里补充。")
extra_details = st.text_input(
    "例如：他脸上的伤疤和手里的红苹果必须保留。",
    placeholder="e.g., The scar on his left cheek must be clearly visible."
)

if st.button("🚀 生成神级 Prompt", type="primary", use_container_width=True):
    if not angle_input:
        st.error("⚠️ 请至少输入期望的镜头角度！")
    else:
        prompt_parts = []
        
        # 1. 核心指令：定义新视角
        prompt_parts.append(f"New Camera Angle: {angle_input.strip()}")
        
        # 2. 锚定主体内容
        if subject_input:
            prompt_parts.append(f"Scene Description: {subject_input.strip()}")
            
        if extra_details:
            prompt_parts.append(f"Crucial Details to Preserve: {extra_details.strip()}")
            
        # 3. 极其严格的限制条件（使用英文，因为底层模型对英文指令理解更精准）
        constraints = """
ABSOLUTE REQUIREMENTS FOR THE GENERATION:
You are operating as a precise 3D virtual camera. Your sole task is to re-render the provided reference image from the new camera angle specified above. 

1. IDENTITY & SUBJECT: The character's exact identity, facial features, hairstyle, clothing design, and body proportions MUST remain 100% identical to the reference image.
2. ENVIRONMENT: The background, surrounding objects, and overall setting must be completely preserved, simply viewed from the new perspective.
3. STYLE & LIGHTING: Maintain the exact same art style, color palette, brushwork/texture, and lighting conditions.

Do NOT alter the character's core action or introduce any new elements. ONLY the camera's viewing angle is allowed to change.
"""
        prompt_parts.append(constraints.strip())
        
        final_prompt = "\\n\\n".join(prompt_parts)
        
        st.success("✅ 生成成功！请复制下方文本：")
        st.code(final_prompt, language="text")
        
        st.info("""
        💡 **在 ComfyUI 中的使用建议：**
        1. 将上述文本粘贴到 `GeminiNanoBanana2` 节点的 `prompt` 输入框中。
        2. 确保原图已连接到 `images` 接口。
        3. 建议将 `thinking_level` 设置为 `HIGH`，让模型有更多时间进行空间视角的计算。
        4. 如果变形严重，可以尝试多次生成（改变 seed）或者在提示词中把 `Scene Description` 描述得更详细。
        """)
