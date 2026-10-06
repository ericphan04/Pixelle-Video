# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pixelle Studio - Trang tạo video AI trực quan, thông minh và dễ sử dụng
Dành riêng cho luồng tạo video hoạt hình 3D / điện ảnh với Muse.ai, giọng đọc tiếng Việt và nhạc nền.
Hỗ trợ AI đọc hiểu nội dung import và tự động phân cảnh, sinh prompt hình ảnh và kịch bản tương tác.
"""

import os
import sys
import time
import json
import re
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure project root is in sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from openai import OpenAI
from loguru import logger

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.utils.async_helpers import run_async
from pixelle_video.config import config_manager
from pixelle_video.services.api_services.video_muse import MuseVideoClient
from pixelle_video.services.video import VideoService
from pixelle_video.models.progress import ProgressEvent

# Setup Page Configuration
st.set_page_config(
    page_title="Pixelle Studio - Video AI 3D",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Preset Styles
STYLE_PRESETS = {
    "3d_pixar": {
        "name": "🌟 Hoạt hình 3D Pixar / Disney (Khuyên dùng)",
        "prompt": (
            "Vibrant 3D animated feature film style, bright natural daylight, rich vibrant colors, "
            "Pixar and Disney aesthetic, clean widescreen composition, smooth natural motion, "
            "crisp textures, highly detailed environment, absolutely no text, no captions, no watermark."
        ),
        "desc": "Phong cách hoạt hình 3D tươi sáng, chuyển động tự nhiên, ánh sáng ấm áp, hình ảnh bắt mắt."
    },
    "cinematic_real": {
        "name": "🎬 Điện ảnh sống động (Cinematic Photoreal)",
        "prompt": (
            "Cinematic photorealistic 8k video, masterpiece, hyper-realistic, dramatic lighting, "
            "smooth natural motion, shallow depth of field, award-winning cinematography, "
            "absolutely no text, no captions, no watermark."
        ),
        "desc": "Phong cách phim điện ảnh thực tế, ánh sáng nghệ thuật và độ sâu trường ảnh cao cấp."
    },
    "anime_shinkai": {
        "name": "🌸 Anime Nhật Bản (Makoto Shinkai Style)",
        "prompt": (
            "Beautiful Makoto Shinkai anime style, vibrant glowing sky, emotional cinematic lighting, "
            "highly detailed hand-drawn aesthetic, smooth anime motion, absolutely no text, no captions, no watermark."
        ),
        "desc": "Phong cách hoạt hình Nhật Bản thơ mộng, bầu trời rực rỡ và cảm xúc sâu lắng."
    },
    "custom": {
        "name": "⚙️ Phong cách tùy chỉnh",
        "prompt": "",
        "desc": "Tự nhập mô tả phong cách thị giác theo ý bạn."
    }
}

# Character Consistency Presets
CHARACTER_PRESETS = {
    "vn_male_student": {
        "name": "Nam sinh Việt Nam (16–17 tuổi, sơ mi trắng, quần xanh)",
        "prompt": (
            "Consistent recurring main character: handsome 16-17 year old Vietnamese high school male student, "
            "neat black hair, bright expressive curious brown eyes, wearing a crisp white collared uniform shirt, "
            "dark navy trousers, and a student backpack."
        )
    },
    "vn_female_student": {
        "name": "Nữ sinh Việt Nam (16–17 tuổi, áo dài trắng / đồng phục nữ)",
        "prompt": (
            "Consistent recurring main character: beautiful 16-17 year old Vietnamese high school female student, "
            "graceful smile, long straight silky black hair, bright brown eyes, wearing a traditional white ao dai uniform."
        )
    },
    "young_office": {
        "name": "Nhân viên trẻ trung (Áo sơ mi thanh lịch)",
        "prompt": (
            "Consistent recurring main character: enthusiastic 24-year-old Asian young professional, "
            "neat hair, confident friendly expression, smart casual white shirt."
        )
    },
    "custom_char": {
        "name": "Tự nhập mô tả nhân vật...",
        "prompt": ""
    }
}

# Voice Presets
VOICE_OPTIONS = {
    "vi-VN-NamMinhNeural": "Nam Minh (Giọng Nam trẻ trung, ấm áp, truyền cảm - Khuyên dùng)",
    "vi-VN-HoaiMyNeural": "Hoài My (Giọng Nữ trong trẻo, nhẹ nhàng, tự nhiên)",
    "en-US-AndrewMultilingualNeural": "Andrew (Tiếng Anh đa ngữ, nam tính)",
    "en-US-AvaMultilingualNeural": "Ava (Tiếng Anh đa ngữ, nữ tính)",
}

# BGM Presets
BGM_OPTIONS = {
    "bgm/default.mp3": "Melodies of Life (Acoustic Guitar & Piano du dương, cảm xúc)",
    "data/bgm/nature_student_bgm.mp3": "Giai điệu thiên nhiên học đường (Tươi sáng, tích cực)",
}

# Sample Topic Scripts
SAMPLE_TOPICS = {
    "Học sinh chung tay bảo vệ môi trường": [
        ("Mỗi ngày đến trường, thiên nhiên luôn ở bên chúng ta. Nhưng bạn có biết môi trường đang phải chịu những gì?",
         "Wide cinematic shot of a lush green high school courtyard in Vietnam, abundant leafy tropical trees, dappled sunlight filtering through green canopy. The handsome Vietnamese student walks peacefully under the shade, curiously following a colorful fluttering butterfly, then gently bending down to admire a fresh dewy leaf. Camera smoothly dollies into his delighted, wonder-filled face."),
        ("Rác nhựa bị vứt bừa bãi làm bẩn đất, sông ngòi và gây nguy hiểm cho các loài sinh vật.",
         "Daytime scene at a canal embankment near the school. Single-use plastic bottles, straws, and plastic bags float on murky water. The main Vietnamese student and a classmate observe the pollution. The boy furrows his brows with genuine concern and points out the trash. Wearing protective yellow gloves and holding trash grabber tongs, both students take initiative to carefully pick up plastic debris along the riverbank."),
        ("Khói bụi từ xe cộ, nhà máy làm ô nhiễm không khí. Chặt phá rừng khiến động vật mất nơi sống.",
         "High school students standing safely on an urban sidewalk watching dense exhaust smoke billowing from busy traffic and distant factory chimneys. Transitioning to an adjacent barren hill with tree stumps, dry cracked soil, and empty bird nests. The main student kneels down and gently touches the dry tree bark with a worried, deeply compassionate expression."),
        ("Hãy bắt đầu từ việc nhỏ: giảm nhựa dùng một lần, phân loại rác, tiết kiệm điện và sử dụng nước vừa đủ.",
         "Cheerful, sunlit classroom and hallway inside the high school. The main Vietnamese student smiles while taking a drink from his reusable stainless steel water bottle, then carefully sorts recyclable paper and bottles into color-coded recycling bins. In the background, a classmate responsibly turns off a running water faucet, and another classmate switches off classroom lights before stepping outside."),
        ("Cùng trồng và chăm sóc cây xanh, dọn rác đúng cách, đi bộ hoặc đạp xe khi phù hợp, và nhắc nhau bảo vệ thiên nhiên.",
         "Inspiring teamwork scene under warm golden sunlight in the school garden and community park. A group of high school students and an encouraging teacher work happily together, digging soil and planting young green trees. The main student smiles warmly with mud on his gardening gloves, handing a healthy young sapling to his classmate while others water the newly planted trees."),
        ("Một hành động nhỏ hôm nay có thể tạo nên thay đổi lớn ngày mai. Bảo vệ môi trường, bắt đầu từ chúng mình!",
         "Emotional and uplifting finale scene during golden hour. The student group stands proudly together around the flourishing young green tree they just planted. A delicate glowing butterfly flutters across the frame; the main student looks up with sparkling eyes full of hope and determination. The camera smoothly pulls back into a wide panoramic view of the vibrant green school campus under a radiant blue sky.")
    ],
    "Khám phá vũ trụ bao la": [
        ("Từ Trái Đất nhỏ bé, con người luôn khao khát ngắm nhìn những vì sao xa xôi.",
         "A starry night sky above a high-tech modern observatory. The student character looks through a massive telescope with eyes wide open in awe, glittering starlight reflecting in his eyes."),
        ("Hệ Mặt Trời của chúng ta ẩn chứa vô vàn bí ẩn kỳ thú đang chờ được khám phá.",
         "Grand cinematic view of the solar system, planets smoothly orbiting the radiant sun, colorful cosmic dust and majestic asteroid belts moving through space."),
        ("Hành trình vươn tới các vì sao bắt đầu từ niềm đam mê học hỏi không ngừng hôm nay!",
         "Uplifting scene of the student smiling beside futuristic spacecraft models in a science laboratory, looking ahead with burning ambition and inspiration.")
    ]
}


def get_llm_client() -> OpenAI:
    """Tạo client OpenAI kết nối với LLM service"""
    cfg = config_manager.config.llm
    api_key = cfg.api_key or "sk-936deff468921c84-2admyf-f3dc07c1"
    base_url = cfg.base_url or "http://localhost:20128/v1"
    return OpenAI(base_url=base_url, api_key=api_key)


def ai_breakdown_storyboard(
    content: str,
    num_scenes: int,
    style_name: str,
    style_prompt: str,
    character_prompt: str
) -> List[Dict[str, str]]:
    """
    AI đọc hiểu nội dung import và tự động phân thành các cảnh video hoàn chỉnh
    Mỗi cảnh gồm lời thuyết minh tiếng Việt và visual prompt tiếng Anh cho Muse.ai
    """
    try:
        cfg = config_manager.config.llm
        client = get_llm_client()
        model = cfg.model or "kr/auto"

        system_prompt = (
            "Bạn là đạo diễn và chuyên gia biên kịch video hoạt hình 3D / điện ảnh hàng đầu thế giới. "
            f"Nhiệm vụ của bạn là đọc và phân tích văn bản người dùng cung cấp, sau đó chia thành đúng {num_scenes} phân cảnh video hoàn chỉnh.\n\n"
            "YÊU CẦU BẮT BUỘC CHO MỖI PHÂN CẢNH:\n"
            "1. 'narration': Câu thuyết minh bằng tiếng Việt tự nhiên, cô đọng, giàu cảm xúc (khoảng 10-20 từ, nhịp đọc 5-8 giây mỗi cảnh).\n"
            "2. 'prompt': Mô tả hình ảnh trực quan chi tiết bằng tiếng Anh (Visual Scene Prompt) cho mô hình video AI (Muse.ai). "
            "Mô tả chi tiết hành động nhân vật, góc máy quay (wide shot, close-up, dolly-in, camera pan...), ánh sáng, bối cảnh môi trường. "
            "TUYỆT ĐỐI KHÔNG có chữ (absolutely no text, no watermark, no captions).\n\n"
            f"Phong cách thị giác: {style_name}\n"
            f"Chi tiết phong cách: {style_prompt}\n"
            f"Nhân vật chính: {character_prompt}\n\n"
            "QUY CHUẨN ĐẦU RA BẮT BUỘC: Chỉ trả về một JSON array hợp lệ, không kèm lời dẫn giải:\n"
            "[\n"
            "  {\"narration\": \"Câu thuyết minh tiếng Việt...\", \"prompt\": \"Cinematic English prompt...\"}\n"
            "]"
        )

        user_prompt = (
            f"Hãy đọc nội dung sau và phân tích thành {num_scenes} phân cảnh video nối tiếp nhau hoàn chỉnh:\n\n"
            f"{content}"
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=2500
        )

        raw = resp.choices[0].message.content or ""
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and len(parsed) > 0:
                clean_scenes = []
                for item in parsed:
                    if isinstance(item, dict) and "narration" in item:
                        clean_scenes.append({
                            "narration": str(item.get("narration", "")).strip(),
                            "prompt": str(item.get("prompt", "")).strip()
                        })
                if clean_scenes:
                    return clean_scenes

        logger.warning(f"Could not parse JSON array from LLM response: {raw[:200]}")
    except Exception as e:
        logger.error(f"AI storyboard breakdown failed: {e}")

    # Fallback thông minh: Tự động tách theo đoạn văn hoặc câu
    logger.info("Using smart rule-based fallback segmenter...")
    lines = [p.strip() for p in re.split(r'[\n\.\?!]+', content) if len(p.strip()) > 10]
    if not lines:
        lines = [content.strip() or "Nội dung phân cảnh video."]
    
    # Gom hoặc chia thành num_scenes
    step = max(1, len(lines) // num_scenes) if len(lines) >= num_scenes else 1
    selected = lines[:num_scenes] if len(lines) >= num_scenes else lines
    
    fallback_scenes = []
    for i, line in enumerate(selected):
        fallback_scenes.append({
            "narration": line,
            "prompt": f"Cinematic shot illustrating the scene: {line}. High quality visual, smooth dynamic motion, warm lighting, absolutely no text."
        })
    return fallback_scenes


def ai_generate_next_scene(
    existing_scenes: List[Dict[str, str]],
    base_content: str,
    style_prompt: str,
    character_prompt: str
) -> Dict[str, str]:
    """AI tự động sinh phân cảnh tiếp theo nối tiếp kịch bản hiện có"""
    try:
        cfg = config_manager.config.llm
        client = get_llm_client()
        model = cfg.model or "kr/auto"

        curr_text = "\n".join([f"Cảnh {i+1}: {s.get('narration')}" for i, s in enumerate(existing_scenes)])

        system_prompt = (
            "Bạn là biên kịch video hoạt hình 3D. Hãy viết tiếp phân cảnh tiếp theo liền mạch với câu chuyện.\n"
            f"Phong cách: {style_prompt}\nNhân vật: {character_prompt}\n"
            "Trả về duy nhất JSON object:\n"
            "{\"narration\": \"Câu thuyết minh tiếng Việt 10-18 từ\", \"prompt\": \"Cinematic English prompt without text\"}"
        )

        user_prompt = (
            f"Các cảnh hiện có:\n{curr_text}\n\n"
            f"Nội dung gốc tham khảo: {base_content[:500]}\n\n"
            f"Hãy viết tiếp Cảnh {len(existing_scenes) + 1}."
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )

        raw = resp.choices[0].message.content or ""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if "narration" in data:
                return {
                    "narration": data["narration"].strip(),
                    "prompt": data.get("prompt", "").strip()
                }
    except Exception as e:
        logger.error(f"Failed to generate next scene: {e}")

    return {
        "narration": f"Hành trình ý nghĩa tiếp tục mở ra những điều tuyệt vời ở phân cảnh {len(existing_scenes) + 1}.",
        "prompt": f"Inspiring cinematic continuation shot for scene {len(existing_scenes) + 1}, emotional lighting, beautiful environment, no text."
    }


def ai_optimize_scene_prompt(
    narration: str,
    style_prompt: str,
    character_prompt: str
) -> str:
    """AI tự động nâng cấp câu thoại tiếng Việt thành visual prompt tiếng Anh chuẩn điện ảnh cho Muse.ai"""
    try:
        cfg = config_manager.config.llm
        client = get_llm_client()
        model = cfg.model or "kr/auto"

        prompt = (
            f"Hãy chuyển câu thoại tiếng Việt sau thành mô tả thị giác tiếng Anh (Visual Prompt) cực kỳ chi tiết cho AI Video (Muse.ai):\n"
            f"Câu thoại: '{narration}'\n"
            f"Phong cách: {style_prompt}\n"
            f"Nhân vật: {character_prompt}\n\n"
            "Yêu cầu: Mô tả chi tiết hành động nhân vật, góc máy (wide shot/close-up/dolly), ánh sáng, biểu cảm, cảnh quan. "
            "Tuyệt đối không có text (absolutely no text, no captions). Chỉ trả về duy nhất đoạn prompt tiếng Anh."
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        return resp.choices[0].message.content.strip().replace('"', '')
    except Exception as e:
        logger.error(f"Failed to optimize scene prompt: {e}")
        return f"Cinematic detailed shot of: {narration}. Beautiful natural lighting, rich colors, smooth motion, no text."


def test_voice_sample(voice: str, speed: float = 1.0) -> Optional[str]:
    """Tạo mẫu giọng đọc nhanh để nghe thử"""
    try:
        import edge_tts
        sample_text = "Xin chào! Đây là bản nghe thử giọng đọc thuyết minh trên hệ thống Pixelle Studio."
        sample_path = _project_root / "temp" / f"sample_{voice}.mp3"
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        
        rate_str = f"{int((speed - 1.0) * 100):+d}%"
        communicate = edge_tts.Communicate(sample_text, voice, rate=rate_str)
        asyncio.run(communicate.save(str(sample_path)))
        return str(sample_path)
    except Exception as e:
        logger.warning(f"Failed to generate voice sample: {e}")
        return None


def render_studio_header():
    """Hiển thị Banner đầu trang và thanh trạng thái kết nối thông minh"""
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1e1e2f 0%, #2a2b40 100%); padding: 22px 28px; border-radius: 14px; border: 1px solid #3d3e58; margin-bottom: 25px;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <h2 style="margin: 0; color: #ffffff; font-weight: 700; font-size: 26px;">
                        ✨ Pixelle Studio — Video Hoạt Hình 3D & AI Generator
                    </h2>
                    <p style="margin: 6px 0 0 0; color: #b0b2c8; font-size: 14px;">
                        Tạo video hoạt hình 3D chuyển động mượt mà, thuyết minh tiếng Việt tự nhiên, tự động phân cảnh kịch bản và nhạc nền đồng bộ.
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Status Bar
    muse_client = MuseVideoClient()
    muse_status = muse_client.check_status()
    is_muse_ready = muse_status.get("loggedIn", False) and muse_status.get("browserRunning", False)
    viewer_id = muse_status.get("viewerId", "")

    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns([1.3, 1.1, 1.1, 1])

    with col_stat1:
        if is_muse_ready:
            st.success(f"🟢 **Muse.ai**: Sẵn sàng (ID: {viewer_id or 'Đã kết nối'})", icon="✅")
        elif muse_status.get("browserRunning"):
            st.warning("🟡 **Muse.ai**: Trình duyệt đang mở (Chưa đăng nhập)", icon="⚠️")
        else:
            st.error("🔴 **Muse.ai**: Chưa mở trình duyệt", icon="🛑")

    with col_stat2:
        st.info("🧠 **AI Kịch bản**: Sẵn sàng (OpenAI / 9router)", icon="🤖")

    with col_stat3:
        st.info("🎙️ **Edge-TTS**: Sẵn sàng (Tiếng Việt)", icon="🔊")

    with col_stat4:
        if not is_muse_ready:
            if st.button("🔑 Mở Muse.ai Đăng Nhập", use_container_width=True, type="primary"):
                with st.spinner("Đang mở trình duyệt Chrome kết nối Muse.ai..."):
                    res = muse_client.connect_browser()
                    if res.get("ok"):
                        st.toast("✅ Đã bật Chrome! Phiên đăng nhập sẽ được lưu tự động vĩnh viễn.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Không thể kết nối Muse: {res.get('error')}")
        else:
            if st.button("🔄 Kiểm tra kết nối", use_container_width=True):
                st.rerun()

    # Expandable Login & Session Management Box
    with st.expander("🔐 Hướng Dẫn & Quản Lý Phiên Đăng Nhập Muse.ai (Tự động lưu Session vĩnh viễn)", expanded=not is_muse_ready):
        exp_col1, exp_col2 = st.columns([2, 1], gap="medium")
        with exp_col1:
            st.markdown(
                """
                - **Cơ chế lưu session**: Hệ thống khởi chạy Chrome với thư mục profile chuyên biệt tại `muse_mcp/.muse-profile` (hoặc chạy script `start_muse_chrome.bat`).
                - **Đăng nhập một lần duy nhất**: Tất cả tài khoản, Cookie và Session đăng nhập trên Muse.ai được Chrome **lưu vĩnh viễn** trong thư mục này. Những lần sử dụng sau hệ thống sẽ tự động nhận diện mà không cần đăng nhập lại.
                - **Cách thực hiện**:
                  1. Bấm nút **'🚀 Bật Cửa Sổ Chrome Muse.ai'** bên cạnh để mở cửa sổ trình duyệt.
                  2. Thực hiện đăng nhập tài khoản của bạn trên trang **Muse.ai**.
                  3. Sau khi thấy trang chủ Muse.ai hiển thị avatar tài khoản của bạn, quay lại đây bấm **'✅ Đã Đăng Nhập Xong (Cập Nhật)'**.
                """
            )
        with exp_col2:
            st.write("")
            if st.button("🚀 Bật Cửa Sổ Chrome Muse.ai", use_container_width=True, type="primary" if not is_muse_ready else "secondary"):
                with st.spinner("Đang khởi động Chrome CDP..."):
                    res = muse_client.connect_browser()
                    if res.get("ok"):
                        st.success("Đã mở Chrome đến muse.ai thành công!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Lỗi: {res.get('error')}")

            st.link_button("🌐 Mở liên kết Muse.ai (Tab mới)", "https://muse.ai", use_container_width=True)

            if st.button("✅ Đã Đăng Nhập Xong (Cập Nhật)", use_container_width=True):
                st.rerun()



def main():
    init_session_state()
    init_i18n()
    
    render_studio_header()

    # Initialize Session Scenes if not present
    if "studio_scenes" not in st.session_state:
        st.session_state.studio_scenes = [
            {"narration": text, "prompt": prompt}
            for text, prompt in SAMPLE_TOPICS["Học sinh chung tay bảo vệ môi trường"]
        ]
    if "imported_content_text" not in st.session_state:
        st.session_state.imported_content_text = ""

    # Tabs for intuitive 3-Step Guided Workflow
    tab_step1, tab_step2, tab_step3 = st.tabs([
        "🎨 Bước 1: Ý tưởng & Thiết lập",
        "📝 Bước 2: Import & Phân cảnh AI (Storyboard)",
        "🚀 Bước 3: Dựng & Xuất Video",
    ])

    # =========================================================================
    # BƯỚC 1: Ý TƯỞNG & THIẾT LẬP
    # =========================================================================
    with tab_step1:
        col_left, col_right = st.columns([1, 1], gap="large")

        with col_left:
            st.subheader("1. Khung hình & Phong cách hình ảnh")
            
            # Aspect Ratio
            aspect_ratio = st.radio(
                "Định dạng video:",
                options=["16:9 Ngang (YouTube, TV, Facebook - 1920x1080)", "9:16 Dọc (TikTok, Reels, Shorts - 1080x1920)"],
                index=0,
                horizontal=True
            )
            is_16_9 = "16:9" in aspect_ratio
            video_width = 1920 if is_16_9 else 1080
            video_height = 1080 if is_16_9 else 1920
            frame_template = "1920x1080/video_default.html" if is_16_9 else "1080x1920/video_default.html"

            # Visual Style Preset
            style_choice = st.selectbox(
                "Phong cách thị giác (Visual Style):",
                options=list(STYLE_PRESETS.keys()),
                format_func=lambda k: STYLE_PRESETS[k]["name"],
                index=0
            )
            selected_style = STYLE_PRESETS[style_choice]
            st.caption(f"💡 {selected_style['desc']}")

            if style_choice == "custom":
                custom_style_prompt = st.text_area(
                    "Mô tả phong cách tùy chỉnh (Tiếng Anh hoặc Tiếng Việt):",
                    value="Vibrant 3D animated film style, bright colors, smooth cinematic lighting",
                    height=80
                )
            else:
                custom_style_prompt = selected_style["prompt"]

            st.divider()

            # Character Consistency
            st.subheader("2. Nhân vật chính đồng nhất (Character Consistency)")
            enable_character = st.checkbox("Giữ ngoại hình nhân vật nhất quán xuyên suốt các cảnh", value=True)
            
            if enable_character:
                char_choice = st.selectbox(
                    "Mẫu nhân vật chính:",
                    options=list(CHARACTER_PRESETS.keys()),
                    format_func=lambda k: CHARACTER_PRESETS[k]["name"],
                    index=0
                )
                if char_choice == "custom_char":
                    character_prompt = st.text_area(
                        "Mô tả nhân vật chi tiết:",
                        value="Handsome 16-17 year old Vietnamese high school male student, neat black hair, crisp white shirt, dark trousers, backpack.",
                        height=80
                    )
                else:
                    character_prompt = CHARACTER_PRESETS[char_choice]["prompt"]
                    with st.expander("Xem chi tiết mô tả nhân vật"):
                        st.write(character_prompt)
            else:
                character_prompt = ""

        with col_right:
            st.subheader("3. Thuyết minh & Âm thanh")
            
            # Voice Selection
            voice_col1, voice_col2 = st.columns([3, 1])
            with voice_col1:
                selected_voice = st.selectbox(
                    "Giọng đọc thuyết minh (Edge-TTS):",
                    options=list(VOICE_OPTIONS.keys()),
                    format_func=lambda k: VOICE_OPTIONS[k],
                    index=0
                )
            with voice_col2:
                st.write("")
                st.write("")
                if st.button("▶️ Nghe thử", use_container_width=True):
                    with st.spinner("Đang tạo âm thanh mẫu..."):
                        sample_audio = test_voice_sample(selected_voice, speed=0.98)
                        if sample_audio and os.path.exists(sample_audio):
                            st.session_state.sample_voice_path = sample_audio

            if "sample_voice_path" in st.session_state and os.path.exists(st.session_state.sample_voice_path):
                st.audio(st.session_state.sample_voice_path)

            voice_speed = st.slider("Tốc độ giọng đọc:", min_value=0.8, max_value=1.2, value=0.98, step=0.02)

            st.divider()

            # BGM Selection
            st.subheader("4. Nhạc nền (Background Music)")
            bgm_choice = st.selectbox(
                "Chọn bản nhạc nền:",
                options=list(BGM_OPTIONS.keys()),
                format_func=lambda k: BGM_OPTIONS[k],
                index=0
            )
            
            bgm_preview_col1, bgm_preview_col2 = st.columns([3, 1])
            with bgm_preview_col1:
                bgm_volume = st.slider("Âm lượng nhạc nền:", min_value=0.05, max_value=0.60, value=0.28, step=0.02,
                                       help="Mức 0.25 - 0.30 cho phép nhạc nền du dương rõ ràng mà không lấn át lời đọc.")
            with bgm_preview_col2:
                st.write("")
                st.write("")
                if st.button("▶️ Nghe nhạc", use_container_width=True):
                    st.session_state.play_bgm = True

            if st.session_state.get("play_bgm") and os.path.exists(bgm_choice):
                st.audio(bgm_choice)

            # Transitions
            st.divider()
            st.subheader("5. Hiệu ứng chuyển cảnh (Transitions)")
            trans_col1, trans_col2 = st.columns([1, 1])
            with trans_col1:
                trans_effect = st.selectbox(
                    "Hiệu ứng chuyển cảnh:",
                    options=["fade", "dissolve", "wipeleft", "wiperight", "slideleft"],
                    index=0,
                    help="Hiệu ứng fade giúp chuyển cảnh nhẹ nhàng, sang trọng và chuẩn điện ảnh."
                )
            with trans_col2:
                trans_duration = st.slider("Thời gian chuyển tiếp (giây):", min_value=0.3, max_value=1.0, value=0.5, step=0.1)

    # =========================================================================
    # BƯỚC 2: IMPORT NỘI DUNG & PHÂN CẢNH AI (STORYBOARD)
    # =========================================================================
    with tab_step2:
        st.subheader("📥 1. Import Nội dung & AI Tự động Phân cảnh")
        st.caption("Dán bài viết, câu chuyện, tài liệu hoặc tải lên tệp văn bản. AI sẽ đọc hiểu, tự động chia thành các phân cảnh chuẩn và sinh visual prompt.")

        import_box = st.container(border=True)
        with import_box:
            import_tab_paste, import_tab_file, import_tab_sample = st.tabs([
                "📋 Dán nội dung trực tiếp",
                "📁 Tải lên tệp (.txt / .md / .srt)",
                "🌟 Nạp kịch bản mẫu nhanh"
            ])

            with import_tab_paste:
                user_imported_text = st.text_area(
                    "Dán nội dung bài viết, ý tưởng hoặc câu chuyện tại đây:",
                    value=st.session_state.imported_content_text,
                    height=130,
                    placeholder="Ví dụ: Trường em vừa tổ chức ngày hội trồng cây bảo vệ môi trường. Các bạn học sinh hào hứng dọn rác bên bờ sông...",
                    key="input_imported_text"
                )
                if user_imported_text != st.session_state.imported_content_text:
                    st.session_state.imported_content_text = user_imported_text

            with import_tab_file:
                uploaded_file = st.file_uploader(
                    "Chọn tệp văn bản trên máy tính:",
                    type=["txt", "md", "srt"],
                    help="Hỗ trợ các tệp văn bản thuần, markdown hoặc phụ đề srt."
                )
                if uploaded_file is not None:
                    try:
                        file_content = uploaded_file.read().decode("utf-8", errors="replace")
                        st.session_state.imported_content_text = file_content
                        st.success(f"Đã đọc tệp `{uploaded_file.name}` ({len(file_content)} ký tự)!")
                    except Exception as e:
                        st.error(f"Không thể đọc file: {e}")

            with import_tab_sample:
                sample_col1, sample_col2 = st.columns([3, 1])
                with sample_col1:
                    chosen_topic = st.selectbox(
                        "Chọn chủ đề có sẵn:",
                        options=list(SAMPLE_TOPICS.keys()),
                        index=0
                    )
                with sample_col2:
                    st.write("")
                    st.write("")
                    if st.button("📥 Dùng chủ đề này", use_container_width=True):
                        st.session_state.studio_scenes = [
                            {"narration": text, "prompt": prompt}
                            for text, prompt in SAMPLE_TOPICS[chosen_topic]
                        ]
                        st.toast(f"Đã nạp {len(st.session_state.studio_scenes)} cảnh mẫu!")
                        st.rerun()

            # AI Breakdown Controls
            st.divider()
            ctrl_col1, ctrl_col2 = st.columns([1, 2])
            with ctrl_col1:
                target_scenes_count = st.slider(
                    "Số phân cảnh mong muốn tạo ra:",
                    min_value=2,
                    max_value=10,
                    value=min(max(len(st.session_state.studio_scenes), 4), 6),
                    step=1,
                    help="Mỗi cảnh tương ứng ~5-8 giây video. 5-6 cảnh sẽ tạo ra video ~40 giây chuẩn."
                )

            with ctrl_col2:
                st.write("")
                st.write("")
                ai_analyze_btn = st.button(
                    "🪄 AI ĐỌC HIỂU & TỰ ĐỘNG PHÂN CẢNH (STORYBOARD)",
                    type="primary",
                    use_container_width=True
                )

            if ai_analyze_btn:
                content_to_process = st.session_state.imported_content_text.strip()
                if not content_to_process:
                    st.warning("Vui lòng nhập hoặc tải lên nội dung văn bản trước khi yêu cầu AI phân cảnh!")
                else:
                    with st.spinner("🤖 AI đang đọc hiểu nội dung, tối ưu lời thoại tiếng Việt và tạo visual prompt tiếng Anh..."):
                        new_scenes = ai_breakdown_storyboard(
                            content=content_to_process,
                            num_scenes=target_scenes_count,
                            style_name=selected_style["name"],
                            style_prompt=custom_style_prompt,
                            character_prompt=character_prompt
                        )
                        if new_scenes:
                            st.session_state.studio_scenes = new_scenes
                            st.toast(f"🎉 AI đã tạo thành công {len(new_scenes)} phân cảnh!")
                            st.rerun()

        # =====================================================================
        # 2. BẢNG PHÂN CẢNH TƯƠNG TÁC (INTERACTIVE SCENES LIST)
        # =====================================================================
        st.write("")
        st.subheader("🎬 2. Bảng Phân Cảnh Tương Tác (Chỉnh sửa theo ý bạn)")
        
        scenes = st.session_state.studio_scenes
        est_duration = sum([max(5.0, len(s.get("narration", "").split()) * 0.45) for s in scenes])
        
        top_bar_col1, top_bar_col2 = st.columns([3, 2])
        with top_bar_col1:
            st.markdown(f"**Tổng số:** `{len(scenes)} cảnh` | **Thời lượng ước tính:** `~{est_duration:.0f} giây`")
        with top_bar_col2:
            sub_col1, sub_col2 = st.columns([1, 1])
            with sub_col1:
                if st.button("➕ Thêm cảnh mới", use_container_width=True):
                    st.session_state.studio_scenes.append({
                        "narration": f"Nội dung phân cảnh {len(scenes) + 1}...",
                        "prompt": f"Detailed cinematic shot for scene {len(scenes) + 1}, beautiful lighting, no text."
                    })
                    st.rerun()
            with sub_col2:
                if st.button("✨ AI Sinh cảnh tiếp theo", use_container_width=True):
                    with st.spinner("AI đang viết tiếp phân cảnh tiếp theo..."):
                        next_sc = ai_generate_next_scene(
                            existing_scenes=scenes,
                            base_content=st.session_state.imported_content_text,
                            style_prompt=custom_style_prompt,
                            character_prompt=character_prompt
                        )
                        st.session_state.studio_scenes.append(next_sc)
                        st.toast("Đã thêm phân cảnh mới liền mạch!")
                        st.rerun()

        scenes_to_delete = []
        move_up_idx = None
        move_down_idx = None
        optimize_prompt_idx = None

        for idx, scene in enumerate(scenes):
            with st.container(border=True):
                head_col1, head_col2, head_col3, head_col4, head_col5 = st.columns([4, 1, 1, 1.8, 1])
                with head_col1:
                    st.markdown(f"**🎬 Phân cảnh {idx + 1}**")
                with head_col2:
                    if idx > 0 and st.button("⬆️", key=f"up_{idx}", help="Di chuyển lên"):
                        move_up_idx = idx
                with head_col3:
                    if idx < len(scenes) - 1 and st.button("⬇️", key=f"down_{idx}", help="Di chuyển xuống"):
                        move_down_idx = idx
                with head_col4:
                    if st.button("🪄 Tối ưu prompt", key=f"opt_{idx}", help="AI tự viết lại visual prompt tiếng Anh chuẩn điện ảnh từ câu thoại này"):
                        optimize_prompt_idx = idx
                with head_col5:
                    if len(scenes) > 1 and st.button("🗑️", key=f"del_{idx}", help="Xóa cảnh này"):
                        scenes_to_delete.append(idx)

                sc_col1, sc_col2 = st.columns([1, 1], gap="medium")
                with sc_col1:
                    new_narration = st.text_area(
                        f"Lời đọc thuyết minh (Tiếng Việt) - Cảnh {idx + 1}:",
                        value=scene.get("narration", ""),
                        height=95,
                        key=f"narr_{idx}"
                    )
                    scene["narration"] = new_narration
                with sc_col2:
                    new_prompt = st.text_area(
                        f"Mô tả hình ảnh (Visual Prompt Tiếng Anh) - Cảnh {idx + 1}:",
                        value=scene.get("prompt", ""),
                        height=95,
                        key=f"prompt_{idx}"
                    )
                    scene["prompt"] = new_prompt

        # Handle scene interactions
        if optimize_prompt_idx is not None:
            target_sc = scenes[optimize_prompt_idx]
            with st.spinner(f"AI đang tối ưu prompt hình ảnh cho Cảnh {optimize_prompt_idx + 1}..."):
                opt_prompt = ai_optimize_scene_prompt(
                    narration=target_sc.get("narration", ""),
                    style_prompt=custom_style_prompt,
                    character_prompt=character_prompt
                )
                target_sc["prompt"] = opt_prompt
                st.toast(f"Đã cập nhật prompt mới cho Cảnh {optimize_prompt_idx + 1}!")
                st.rerun()

        if move_up_idx is not None:
            scenes[move_up_idx - 1], scenes[move_up_idx] = scenes[move_up_idx], scenes[move_up_idx - 1]
            st.rerun()

        if move_down_idx is not None:
            scenes[move_down_idx + 1], scenes[move_down_idx] = scenes[move_down_idx], scenes[move_down_idx + 1]
            st.rerun()

        if scenes_to_delete:
            for idx in sorted(scenes_to_delete, reverse=True):
                st.session_state.studio_scenes.pop(idx)
            st.rerun()

    # =========================================================================
    # BƯỚC 3: DỰNG & XUẤT VIDEO
    # =========================================================================
    with tab_step3:
        st.subheader("Dựng và xuất Video hoàn chỉnh")
        
        # Summary Box
        total_scenes_cnt = len(st.session_state.studio_scenes)
        st.info(
            f"📋 **Thông số dự án:** Định dạng: **{'16:9 (1920x1080)' if is_16_9 else '9:16 (1080x1920)'}** | "
            f"Số cảnh: **{total_scenes_cnt}** | Giọng đọc: **{selected_voice}** | "
            f"Chuyển cảnh: **{trans_effect} ({trans_duration}s)** | Âm lượng nhạc: **{int(bgm_volume*100)}%**"
        )

        generate_btn = st.button(
            "🚀 BẮT ĐẦU TẠO VIDEO HOÀN CHỈNH (MUSE.AI 3D)",
            type="primary",
            use_container_width=True
        )

        progress_container = st.container()
        result_container = st.container()

        if generate_btn:
            # Check Muse connection
            status = muse_client.check_status()
            if not status.get("loggedIn"):
                st.error("Muse.ai chưa được đăng nhập! Vui lòng bấm nút 'Mở Muse.ai' ở đầu trang để đăng nhập trước khi tạo video.")
                st.stop()

            with progress_container:
                st.write("---")
                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.markdown("⏳ **Đang khởi tạo dự án Pixelle Studio...**")

            # Prepare prompts with style & character consistency
            full_prompts = []
            for scene in st.session_state.studio_scenes:
                parts = []
                if custom_style_prompt:
                    parts.append(custom_style_prompt.strip())
                if character_prompt:
                    parts.append(character_prompt.strip())
                if scene["prompt"]:
                    parts.append(scene["prompt"].strip())
                full_prompts.append(" ".join(parts))

            narrations = [s["narration"] for s in st.session_state.studio_scenes]
            script_full = "\n".join(narrations)

            def studio_progress(event: ProgressEvent):
                pct = int(event.progress * 100) if event.progress is not None else 0
                frame_info = f" [Cảnh {event.frame_current}/{event.frame_total}]" if event.frame_current else ""
                step_info = f" [Bước {event.step}]" if event.step else ""
                action = event.action or event.event_type or "Đang xử lý"
                progress_bar.progress(min(pct / 100.0, 1.0))
                status_text.markdown(f"**[{pct:02d}%]{frame_info}{step_info}** {action}...")

            try:
                pixelle = get_pixelle_video()
                pipeline = pixelle.pipelines["standard"]

                start_t = time.time()
                result = run_async(pipeline(
                    text=script_full,
                    mode="fixed",
                    split_mode="line",
                    title="Pixelle Studio Video",
                    frame_template=frame_template,
                    media_workflow="api/muse/muse-video",
                    media_width=video_width,
                    media_height=video_height,
                    api_video_params={"video_ratio": "16:9" if is_16_9 else "9:16", "resolution": "1080P"},
                    image_prompts=full_prompts,
                    tts_voice=selected_voice,
                    tts_inference_mode="local",
                    tts_speed=voice_speed,
                    progress_callback=studio_progress,
                    transition_name=trans_effect,
                    transition_duration=trans_duration,
                    bgm_path=bgm_choice,
                    bgm_volume=bgm_volume,
                    bgm_mode="loop",
                ))

                elapsed = time.time() - start_t
                progress_bar.progress(1.0)
                status_text.success(f"🎉 **Hoàn thành xuất video thành công sau {elapsed:.1f} giây!**")

                st.session_state.last_studio_video = result.video_path

            except Exception as e:
                logger.error(f"Error generating studio video: {e}")
                st.error(f"Đã xảy ra lỗi khi tạo video: {e}")
                st.stop()

        # Display Result if available
        if "last_studio_video" in st.session_state and os.path.exists(st.session_state.last_studio_video):
            final_video_path = st.session_state.last_studio_video
            with result_container:
                st.write("---")
                st.subheader("🎬 Kết quả Video hoàn thiện:")
                
                # Video Player
                st.video(final_video_path)

                # Info & Download Buttons
                stat_size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
                vs = VideoService()
                stat_duration = vs._get_video_duration(final_video_path)

                inf_col1, inf_col2, inf_col3 = st.columns([1, 1, 1])
                with inf_col1:
                    st.metric("Thời lượng", f"{stat_duration:.1f} giây")
                with inf_col2:
                    st.metric("Dung lượng", f"{stat_size_mb:.2f} MB")
                with inf_col3:
                    st.metric("Độ phân giải", f"{video_width}x{video_height}")

                with open(final_video_path, "rb") as f:
                    video_bytes = f.read()

                btn_col1, btn_col2 = st.columns([1, 1])
                with btn_col1:
                    st.download_button(
                        label="📥 TẢI XUỐNG VIDEO (.MP4)",
                        data=video_bytes,
                        file_name=f"Pixelle_Studio_{Path(final_video_path).stem}.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                        type="primary"
                    )
                with btn_col2:
                    st.info(f"📁 **Vị trí lưu trên máy:** `{final_video_path}`")


if __name__ == "__main__":
    main()
