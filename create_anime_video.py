"""
Script tạo video Anime: CHIẾC LÁ CỦA NIỀM TIN
Sử dụng Pixelle Video Pipeline kết hợp Muse.ai (MUSE_MCP) và Edge-TTS tiếng Việt.
"""

import asyncio
import os
import sys
from pathlib import Path
from loguru import logger
from pixelle_video.service import PixelleVideoCore
from pixelle_video.models.progress import ProgressEvent

async def main():
    logger.info("🎬 Khởi tạo hệ thống Pixelle-Video...")
    core = PixelleVideoCore()
    await core.initialize()
    pipeline = core.pipelines["standard"]

    title = "CHIẾC LÁ CỦA NIỀM TIN"

    # 6 phân cảnh lời thoại và lời kể tiếng Việt
    narrations = [
        "Chiếc ghế cạnh Minh đã trống suốt một tuần. Lan bị ốm, bỏ lỡ cả cuộc thi vẽ mà bạn mong chờ.",
        "Chắc mình không kịp hoàn thành nữa… Minh nhìn bức tranh dang dở, rồi nhìn chiếc lá ngoài cửa sổ.",
        "Cậu chợt nghĩ: nếu một chiếc lá có thể rơi, những chiếc lá khác vẫn có thể mọc lên.",
        "Cả lớp đang chờ cậu trở lại. Bức tranh này cũng vậy! Lần đầu tiên sau nhiều ngày, Lan cầm bút.",
        "Vài ngày sau, Lan trở lại trường. Bức tranh đã hoàn thành, còn chiếc lá vàng được giữ giữa những trang sổ.",
        "Minh hiểu rằng, đôi khi một lời động viên nhỏ cũng giúp người khác có thêm niềm tin. Và tình bạn khiến những ngày buồn trở nên dịu dàng. Một chút quan tâm, một niềm tin được giữ lại."
    ]

    # Visual Prompts phong cách Anime Nhật Bản (Makoto Shinkai), đồng nhất nhân vật và trang phục
    prompts = [
        # Cảnh 1 — Chiếc ghế trống
        (
            "Beautiful Makoto Shinkai anime style, emotional Japanese animation, masterpiece. "
            "Bright warm morning sunlight streaming through the large high school classroom windows. "
            "Minh, a 14-year-old Vietnamese 8th grade schoolboy with short neat black hair, expressive curious brown eyes, "
            "wearing a crisp white collared uniform shirt and dark navy trousers, sitting at his wooden desk and looking with "
            "worried, longing eyes at the empty wooden chair and desk beside him. On the empty desk rests an open sketchbook with pencils. "
            "Golden dust motes floating in warm light, emotional cinematic shot, slow zoom in on Minh's concerned face, "
            "exquisitely detailed hand-drawn anime aesthetic, absolutely no text, no watermark, no captions."
        ),
        # Cảnh 2 — Bức tranh dang dở
        (
            "Beautiful Makoto Shinkai anime style, touching emotional Japanese animation. "
            "Inside a cozy sunlit bedroom. Lan, a gentle 14-year-old schoolgirl with soft shoulder-length dark hair, "
            "sitting quietly by an open window, in front of an unfinished drawing of a bare branch. "
            "Minh in his white school uniform stands beside her with deep sympathy and care. Outside in the courtyard, "
            "a single golden autumn leaf gently flutters on a tree branch in the soft breeze. "
            "Melancholic yet warm atmosphere, tender lighting, detailed anime artwork, absolutely no text, no watermark, no captions."
        ),
        # Cảnh 3 — Một ý tưởng nhỏ
        (
            "Beautiful Makoto Shinkai anime style, uplifting Japanese animation. "
            "Minh bends down in the sunny green school courtyard to gently pick up a golden fallen leaf from the grass, "
            "his eyes sparkling with sudden bright inspiration. Cut to the lively warm classroom where friendly classmates "
            "gather around a large tree-shaped paper card, happily drawing and writing colorful encouraging notes on paper leaves. "
            "Warm afternoon glow, cheerful heartwarming atmosphere, smooth anime motion, highly detailed, absolutely no text, no watermark, no captions."
        ),
        # Cảnh 4 — Cây tình bạn
        (
            "Beautiful Makoto Shinkai anime style, deeply moving Japanese animation. "
            "Soft golden afternoon glow through the window. Minh warmly presents the handmade tree-shaped friendship card covered with "
            "colorful paper leaves to Lan. Lan softly caresses the card with touching warmth, tears of gratitude shining in her eyes, "
            "a tender hopeful smile appearing on her face. Beside her, she picks up her colored drawing pencil for the first time in days. "
            "Heartfelt emotional scene, beautiful hand-drawn anime aesthetic, exquisite colors, absolutely no text, no watermark, no captions."
        ),
        # Cảnh 5 — Sắc màu trở lại
        (
            "Beautiful Makoto Shinkai anime style, vibrant joyful Japanese animation. "
            "Close-up of Lan happily painting lush vibrant green leaves onto her tree canvas, bringing the artwork to life with glowing colors. "
            "Transition to the sunny classroom a few days later: Lan happily walking back into class with a radiant smile, while Minh cheerfully "
            "pulls out the chair for her as joyful classmates wave and welcome her back. Uplifting bright atmosphere, sparkling sunlight, "
            "smooth fluid anime movement, masterwork animation, absolutely no text, no watermark, no captions."
        ),
        # Cảnh 6 — Điều còn ở lại
        (
            "Beautiful Makoto Shinkai anime style, grand cinematic finale. "
            "Minh and Lan proudly hanging the fully completed, vibrant tree painting onto the classroom bulletin board together. "
            "The camera smoothly pulls back into a wide cinematic shot, revealing the whole classroom of smiling friends bathed in "
            "radiant, warm golden morning sunshine. Emotional heartwarming ending, atmospheric depth of field, stunning anime sky visible through windows, "
            "glorious hand-drawn aesthetic, absolutely no text, no watermark, no captions."
        )
    ]

    script_full = "\n".join(narrations)

    def on_progress(event: ProgressEvent):
        pct = int(event.progress * 100) if event.progress is not None else 0
        cur = f" [Cảnh {event.frame_current}/{event.frame_total}]" if event.frame_current else ""
        step = f" [{event.step}]" if event.step else ""
        action = event.action or event.event_type or "Processing"
        logger.info(f"⏳ [{pct:02d}%]{cur}{step} {action}")

    logger.info(f"🚀 Bắt đầu quá trình tạo video '{title}' (6 cảnh, chuẩn 16:9)...")

    result = await pipeline(
        text=script_full,
        mode="fixed",
        split_mode="line",
        title=title,
        frame_template="1920x1080/video_default.html",
        media_workflow="api/muse/muse-video",
        media_width=1920,
        media_height=1080,
        api_video_params={"video_ratio": "16:9", "resolution": "1080P"},
        image_prompts=prompts,
        tts_voice="vi-VN-NamMinhNeural",
        tts_inference_mode="local",
        tts_speed=1.05,
        progress_callback=on_progress,
        transition_name="fade",
        transition_duration=0.5,
        bgm_path="bgm/default.mp3",
        bgm_volume=0.22,
        bgm_mode="loop"
    )

    logger.success(f"🎉 XUẤT VIDEO HOÀN TẤT THÀNH CÔNG!")
    logger.success(f"📁 Video lưu tại: {result.video_path}")
    print(f"\n==========================================")
    print(f"VIDEO HOÀN TẤT: {result.video_path}")
    print(f"==========================================\n")

if __name__ == "__main__":
    asyncio.run(main())
