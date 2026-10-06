"""JPEG preparation and signed Cloudinary uploads. Originals are never modified."""
import hashlib
import math
import re
import time
import uuid
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

EXTENSIONS = {".jpg", ".jpeg", ".png"}


def prepare_image(path, ratio=None):
    path = Path(path)
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError("JPG 또는 PNG 사진을 선택해 주세요.")
    try:
        with Image.open(path) as source:
            if source.format not in {"JPEG", "PNG"}:
                raise ValueError("실제 파일 형식이 JPG 또는 PNG가 아닙니다.")
            source = ImageOps.exif_transpose(source)
            source.thumbnail((1440, 1440), Image.Resampling.LANCZOS)
            rgba = source.convert("RGBA")
            picture = Image.new("RGB", rgba.size, "white")
            picture.paste(rgba, mask=rgba.getchannel("A"))
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("사진을 읽을 수 없습니다. 파일이 손상되었거나 너무 큰지 확인해 주세요.") from None
    width, height = picture.size
    target = ratio if ratio is not None else max(0.8, min(1.91, width / height))
    if not 0.8 <= target <= 1.91:
        raise ValueError("사진 비율은 4:5부터 1.91:1 사이여야 합니다.")
    # Determine the bounded canvas first, so extreme panoramas cannot allocate huge padding.
    if target >= 1:
        canvas_width = min(1440, max(width, math.ceil(height * target)))
        canvas_height = math.ceil(canvas_width / target)
    else:
        canvas_height = min(1440, max(height, math.ceil(width / target)))
        canvas_width = math.ceil(canvas_height * target)
    canvas_width = max(canvas_width, math.ceil(canvas_height * 0.8))
    canvas_height = max(canvas_height, math.ceil(canvas_width / 1.91))
    picture.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    canvas.paste(picture, ((canvas_width - picture.width) // 2, (canvas_height - picture.height) // 2))
    for quality in (92, 85, 75, 65):
        buffer = BytesIO()
        canvas.save(buffer, "JPEG", quality=quality, optimize=True)
        if buffer.tell() <= 8_000_000:
            return buffer.getvalue()
    raise ValueError("사진을 8MB 이하로 줄이지 못했습니다. 다른 사진을 선택해 주세요.")


class Cloudinary:
    def __init__(self, cloud_name, api_key, api_secret):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cloud_name) or not api_key or not api_secret:
            raise ValueError("설정에서 Cloudinary 이름과 API 키·비밀키를 입력해 주세요.")
        self.base = f"https://api.cloudinary.com/v1_1/{cloud_name}/image"
        self.api_key, self.api_secret = api_key, api_secret

    def request(self, action, parameters, files=None):
        parameters = {**parameters, "timestamp": str(int(time.time()))}
        signature = "&".join(f"{key}={parameters[key]}" for key in sorted(parameters))
        data = {**parameters, "api_key": self.api_key,
                "signature": hashlib.sha1((signature + self.api_secret).encode()).hexdigest()}
        try:
            response = requests.post(f"{self.base}/{action}", data=data, files=files, timeout=(10, 60))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise ValueError("이미지 호스팅에 연결하지 못했습니다. 인터넷과 Cloudinary 설정을 확인해 주세요.") from None

    def upload(self, jpeg, public_id):
        result = self.request("upload", {"public_id": public_id},
                              {"file": ("image.jpg", jpeg, "image/jpeg")})
        url = result.get("secure_url", "")
        if not url.startswith("https://"):
            raise ValueError("이미지 호스팅 주소를 받지 못했습니다.")
        return url

    def delete(self, public_id):
        result = self.request("destroy", {"public_id": public_id, "invalidate": "true"})
        if result.get("result") not in {"ok", "not found"}:
            raise ValueError("임시 사진을 삭제하지 못했습니다. Cloudinary에서 정리해 주세요.")

    def test_connection(self):
        public_id = f"insta-uploader/test-{uuid.uuid4().hex}"
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, "JPEG")
        try:
            self.upload(buffer.getvalue(), public_id)
        finally:
            self.delete(public_id)
        return "Cloudinary 연결 및 삭제 확인 완료"
