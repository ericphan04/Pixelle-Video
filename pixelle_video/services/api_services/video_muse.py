"""
Muse.ai Video Generation Client (via MUSE_MCP Bridge)
Communicates with the Node.js MUSE_MCP HTTP shim on 127.0.0.1:8787.
"""

import os
import shutil
import time
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
from loguru import logger
from .config import Config

# Auto-ensure FFmpeg and ffprobe are in PATH
_gyan_bin = r"C:\Users\Ericc\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin"
if os.path.exists(_gyan_bin) and _gyan_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_gyan_bin};{os.environ.get('PATH', '')}"


class MuseVideoClient:
    """
    Client for generating video clips via the MUSE_MCP bridge.
    Uses async job submission and polling for reliable, non-blocking execution.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """
        Initialize MuseVideoClient.
        
        Args:
            base_url: Base URL of MUSE_MCP HTTP shim (e.g. http://127.0.0.1:8787/v1)
            timeout: Max timeout in seconds for job completion
        """
        self.base_url = (base_url or Config.MUSE_BASE_URL or "http://127.0.0.1:8787/v1").rstrip("/")
        # Remove trailing /v1 if root endpoint is needed
        if self.base_url.endswith("/v1"):
            self.root_url = self.base_url[:-3]
        else:
            self.root_url = self.base_url
            self.base_url = f"{self.root_url}/v1"

        self.timeout = float(timeout or Config.MUSE_TIMEOUT or 300.0)

    def check_status(self) -> Dict[str, Any]:
        """
        Query MUSE_MCP status endpoint.
        
        Returns:
            dict containing browserRunning, loggedIn, viewerId, composerReady, etc.
        """
        url = f"{self.base_url}/muse/status"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.warning(f"Failed to check Muse status at {url}: {e}")
            return {"ok": False, "error": str(e), "loggedIn": False, "browserRunning": False}

    def connect_browser(self) -> Dict[str, Any]:
        """
        Launch Chrome connected to CDP or navigate to muse.ai.
        The browser profile permanently saves login session and cookies.
        
        Returns:
            dict with browser status and loggedIn state
        """
        url = f"{self.base_url}/muse/connect"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url)
                if resp.status_code == 200:
                    return resp.json()
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.error(f"Failed to connect Muse browser at {url}: {e}")
            return {"ok": False, "error": str(e), "loggedIn": False, "browserRunning": False}

    def generate_video(
        self,
        prompt: str,
        image_path: Optional[str] = None,
        save_path: Optional[str] = None,
        output_path: Optional[str] = None,
        model: str = "muse-video",
        duration: int = 5,
        video_ratio: str = "9:16",
        resolution: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: int = 30,
        keep_clip_audio: bool = False,
        **kwargs
    ) -> str:
        """
        Generate a video clip from Muse.ai via MUSE_MCP shim.
        
        Args:
            prompt: Text prompt describing the video scene
            image_path: Optional reference/start image path
            save_path: Destination path for normalized MP4 clip (or output_path)
            model: Model identifier ("muse-video", "muse", etc.)
            duration: Target duration in seconds
            video_ratio: Video aspect ratio ("9:16", "16:9", "1:1")
            resolution: Resolution label ("720P", "1080P")
            width: Target width in pixels
            height: Target height in pixels
            fps: Target output frame rate (default 30)
            keep_clip_audio: Whether to preserve original audio from clip
            
        Returns:
            Path to the saved normalized video file
        """
        target_save_path = save_path or output_path
        if not target_save_path:
            raise ValueError("save_path or output_path is required")
        save_path = target_save_path

        logger.info(f"MuseVideoClient: Requesting video generation. Prompt: '{prompt[:60]}...'")

        # 1. Verify status before submitting
        st = self.check_status()
        if not st.get("loggedIn"):
            err_msg = (
                "Meta Muse is not logged in in the Chrome window. "
                "Please sign in to Meta in the opened Chrome window before generating videos."
            )
            logger.error(f"MuseVideoClient: {err_msg}")
            raise RuntimeError(f"[auth_required] {err_msg}")

        # 2. Submit job
        submit_url = f"{self.base_url}/muse/jobs"
        payload = {
            "prompt": prompt,
            "timeoutMs": int(self.timeout * 1000),
        }
        if image_path and os.path.exists(image_path):
            payload["file"] = os.path.abspath(image_path)

        try:
            with httpx.Client(timeout=30.0) as client:
                submit_resp = client.post(submit_url, json=payload)
                if submit_resp.status_code not in (200, 202):
                    raise RuntimeError(f"Job submission failed: HTTP {submit_resp.status_code} - {submit_resp.text}")
                submit_data = submit_resp.json()
        except Exception as e:
            logger.error(f"MuseVideoClient: Failed to submit job to {submit_url}: {e}")
            raise

        job_id = submit_data.get("jobId")
        if not job_id:
            raise RuntimeError(f"MUSE_MCP did not return a jobId: {submit_data}")

        logger.info(f"MuseVideoClient: Job submitted successfully. Job ID: {job_id}")

        # 3. Poll job status
        poll_url = f"{self.base_url}/muse/jobs/{job_id}"
        poll_interval = 2.5
        start_time = time.time()
        deadline = start_time + self.timeout

        downloaded_media_path = None
        job_result = None

        with httpx.Client(timeout=15.0) as client:
            while time.time() < deadline:
                time.sleep(poll_interval)
                try:
                    resp = client.get(poll_url)
                    if resp.status_code != 200:
                        logger.warning(f"Poll {job_id} returned HTTP {resp.status_code}")
                        continue
                    data = resp.json()
                    status = data.get("status")

                    if status == "completed":
                        job_result = data.get("result", {})
                        downloaded_media_path = job_result.get("mediaPath")
                        logger.success(f"MuseVideoClient: Job {job_id} completed successfully in {time.time() - start_time:.1f}s")
                        break
                    elif status == "failed":
                        err_info = data.get("error", {})
                        code = err_info.get("code", "generation_error")
                        message = err_info.get("message", "Unknown error")
                        logger.error(f"MuseVideoClient: Job {job_id} failed [{code}]: {message}")
                        raise RuntimeError(f"[{code}] {message}")
                    else:
                        logger.debug(f"MuseVideoClient: Job {job_id} status: {status} ({time.time() - start_time:.1f}s)")
                except httpx.RequestError as req_err:
                    logger.warning(f"Network error polling {job_id}: {req_err}")

        # Resolve downloaded file path locally or via download URL
        local_media_path = None
        if downloaded_media_path and os.path.exists(downloaded_media_path):
            local_media_path = downloaded_media_path
        else:
            filename = (job_result or {}).get("filename") or (os.path.basename(downloaded_media_path) if downloaded_media_path else None)
            candidates = []
            if filename:
                candidates.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "muse_mcp", "downloads", filename)))
                candidates.append(os.path.abspath(os.path.join(os.getcwd(), "muse_mcp", "downloads", filename)))
                candidates.append(os.path.abspath(os.path.join(os.getcwd(), "downloads", filename)))

            for cand in candidates:
                if os.path.exists(cand) and os.path.getsize(cand) > 0:
                    local_media_path = cand
                    break

            # If still not found locally, fetch via HTTP from muse-mcp
            if not local_media_path and filename:
                dl_url = f"{self.root_url}/downloads/{filename}"
                dest_dir = os.path.abspath(os.path.join(os.getcwd(), "muse_mcp", "downloads"))
                os.makedirs(dest_dir, exist_ok=True)
                dest_file = os.path.join(dest_dir, filename)
                try:
                    logger.info(f"Downloading clip via HTTP: {dl_url} -> {dest_file}")
                    with httpx.Client(timeout=60.0) as dl_client:
                        resp = dl_client.get(dl_url)
                        if resp.status_code == 200:
                            with open(dest_file, "wb") as f:
                                f.write(resp.content)
                            if os.path.exists(dest_file) and os.path.getsize(dest_file) > 0:
                                local_media_path = dest_file
                except Exception as dl_err:
                    logger.warning(f"Failed to download clip via HTTP from {dl_url}: {dl_err}")

        if not local_media_path or not os.path.exists(local_media_path):
            raise TimeoutError(f"[timeout] Muse video generation timed out or file not accessible for job {job_id}")

        downloaded_media_path = local_media_path

        # 4. Normalize output clip (resolution, FPS, codec, audio)
        target_w, target_h = self._resolve_dimensions(video_ratio, resolution, width, height)
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

        target_duration = duration or kwargs.get("duration") or 5.0
        logger.info(f"MuseVideoClient: Normalizing raw clip {downloaded_media_path} -> {save_path} ({target_w}x{target_h} @ {fps}fps, target_duration={target_duration}s)")
        self.normalize_clip(
            input_path=downloaded_media_path,
            output_path=save_path,
            target_width=target_w,
            target_height=target_h,
            target_fps=fps,
            keep_audio=keep_clip_audio,
            duration=target_duration,
        )

        # 5. Verify normalized output with ffprobe
        probe_info = self.probe_file(save_path)
        if not probe_info or probe_info.get("duration", 0) <= 0:
            raise RuntimeError(f"Normalized clip at {save_path} is invalid or has 0s duration")

        logger.success(f"MuseVideoClient: Final clip ready at {save_path} ({probe_info['duration']:.2f}s, {probe_info['size']} bytes)")
        return save_path

    def _resolve_dimensions(
        self,
        ratio: str,
        resolution: Optional[str],
        width: Optional[int],
        height: Optional[int]
    ) -> tuple[int, int]:
        """Determine target width and height in pixels."""
        if width and height:
            return width, height

        is_1080p = (resolution or "").upper() == "1080P"
        ratio_clean = (ratio or "9:16").replace(":", "x")

        if ratio_clean in ("9x16", "9/16", "vertical", "portrait"):
            return (1080, 1920) if is_1080p else (720, 1280)
        elif ratio_clean in ("16x9", "16/9", "horizontal", "landscape"):
            return (1920, 1080) if is_1080p else (1280, 720)
        elif ratio_clean in ("1x1", "square"):
            return (1080, 1080) if is_1080p else (720, 720)
        elif ratio_clean in ("4x3", "4/3"):
            return (1440, 1080) if is_1080p else (960, 720)
        elif ratio_clean in ("3x4", "3/4"):
            return (1080, 1440) if is_1080p else (720, 960)

        return (1080, 1920)

    @staticmethod
    def probe_file(file_path: str) -> Dict[str, Any]:
        """Probe media file using ffprobe."""
        if not os.path.exists(file_path):
            return {}
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration,size,bit_rate:stream=width,height,codec_name,r_frame_rate,codec_type",
                "-of", "json",
                file_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(res.stdout)
            fmt = info.get("format", {})
            streams = info.get("streams", [])
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

            dur = fmt.get("duration")
            return {
                "duration": float(dur) if dur is not None else 0.0,
                "size": int(fmt.get("size", 0)),
                "width": v_stream.get("width"),
                "height": v_stream.get("height"),
                "codec": v_stream.get("codec_name"),
                "has_audio": bool(a_stream),
                "audio_codec": a_stream.get("codec_name"),
            }
        except Exception as e:
            logger.warning(f"ffprobe failed on {file_path}: {e}")
            return {}

    @classmethod
    def normalize_clip(
        cls,
        input_path: str,
        output_path: str,
        target_width: int = 1080,
        target_height: int = 1920,
        target_fps: int = 30,
        keep_audio: bool = False,
        duration: Optional[float] = None,
    ) -> str:
        """
        Normalize video or image clip to exact resolution, FPS, H.264 video codec, and AAC audio.
        Uses scale+pad filter to maintain aspect ratio without distortion.
        Handles both video and static image inputs (looping static images to target duration).
        """
        probe = cls.probe_file(input_path)
        has_audio = probe.get("has_audio", False)
        input_duration = probe.get("duration", 0.0)
        is_image = input_duration <= 0 or input_path.lower().endswith((".webp", ".png", ".jpg", ".jpeg"))

        target_duration = duration or (input_duration if input_duration > 0 else 5.0)

        # Video filter: scale to fit within bounding box, pad remaining with black
        scale_pad_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={target_fps},format=yuv420p"
        )

        cmd = ["ffmpeg", "-y"]
        if is_image:
            cmd.extend(["-loop", "1", "-i", input_path, "-t", str(target_duration)])
        else:
            cmd.extend(["-i", input_path])
            if target_duration and target_duration < input_duration:
                cmd.extend(["-t", str(target_duration)])

        if not (keep_audio and has_audio) or is_image:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])

        cmd.extend([
            "-vf", scale_pad_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
        ])

        if keep_audio and has_audio and not is_image:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

        cmd.append(output_path)

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg normalization failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg normalization failed: {res.stderr}")
        return output_path

    @classmethod
    def launch_browser_debug(cls, profile_dir: Optional[str] = None) -> bool:
        """Launch Chrome with remote debugging on port 9222 and open muse.ai."""
        import subprocess
        import os
        from pathlib import Path
        
        target_profile = profile_dir or str(Path("E:/linhtinh/MUSE_MCP/.muse-profile").resolve())
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        exe = next((p for p in chrome_paths if os.path.exists(p)), None)
        if not exe:
            return False

        # If already listening on port 9222, just return True
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get("http://127.0.0.1:9222/json/version")
                if resp.status_code == 200:
                    return True
        except Exception:
            pass

        bat_path = Path("E:/linhtinh/Pixelle-Video/start_muse_chrome.bat").resolve()
        # Use schtasks /it for interactive Windows desktop display
        try:
            subprocess.run([
                "schtasks", "/create", "/tn", "OpenMuse",
                "/tr", str(bat_path),
                "/sc", "once", "/st", "23:59", "/f", "/it"
            ], capture_output=True, text=True, timeout=5)
            subprocess.run(["schtasks", "/run", "/tn", "OpenMuse"], capture_output=True, text=True, timeout=5)
            subprocess.run(["schtasks", "/delete", "/tn", "OpenMuse", "/f"], capture_output=True, text=True, timeout=5)
            return True
        except Exception as e:
            logger.warning(f"schtasks interactive launch failed: {e}")

        try:
            subprocess.Popen([
                exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={target_profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "https://muse.ai"
            ])
            return True
        except Exception as ex:
            logger.error(f"Fallback launch failed: {ex}")
            return False

    def connect_bridge(self) -> Dict[str, Any]:
        """Trigger bridge to connect/attach to Chrome at https://muse.ai and check status."""
        self.launch_browser_debug()
        url = f"{self.base_url}/muse/connect"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.warning(f"Failed to post /muse/connect: {e}")
        return self.check_status()
