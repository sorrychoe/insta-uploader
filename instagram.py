"""Instagram Login API only; publishing is never automatically retried."""
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

from ai import validate_caption, validate_product
from images import Cloudinary, prepare_image
import storage


class InstagramError(ValueError):
    pass


class PublishUncertain(InstagramError):
    pass


class Instagram:
    def __init__(self, user_id, token, version="v24.0"):
        if not re.fullmatch(r"\d+", user_id) or not token:
            raise InstagramError("설정에서 인스타 계정 ID와 장기 액세스 토큰을 입력해 주세요.")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise InstagramError("API 버전은 v24.0 형태로 입력해 주세요.")
        self.user_id, self.token = user_id, token
        self.base = f"https://graph.instagram.com/{version}"

    def request(self, method, path, timeout=30, **parameters):
        publishing = path.endswith("/media_publish")
        try:
            response = requests.request(
                method, f"{self.base}/{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                **({"params": parameters} if method == "GET" else {"data": parameters}),
                timeout=timeout,
            )
            if publishing and response.status_code >= 500:
                raise PublishUncertain("게시 결과를 확인하지 못했습니다. 재시도 전에 인스타 계정을 확인해 주세요.")
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, PublishUncertain):
                raise
            kind = PublishUncertain if publishing else InstagramError
            raise kind("인스타 응답을 확인하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
        if "error" in payload or not response.ok:
            error = payload.get("error", {})
            if not isinstance(error, dict):
                error = {}
            code = error.get("code")
            if code == 190:
                raise InstagramError("인스타 연결이 만료되었거나 해제되었습니다. 설정에서 새 장기 토큰으로 다시 연결해 주세요.")
            if code in (10, 200):
                raise InstagramError("Meta 앱에 instagram_business_basic 및 instagram_business_content_publish 권한이 있는지 확인해 주세요.")
            if code == 100:
                raise InstagramError("인스타 계정 ID나 API 버전이 올바른지, Instagram Login용 계정 ID인지 확인해 주세요.")
            if code in (4, 9, 17, 32, 613):
                raise InstagramError("인스타 요청 또는 게시 한도에 도달했습니다. 잠시 후 연결 테스트로 남은 한도를 확인해 주세요.")
            # Meta's error message can echo request data; expose only safe error identifiers.
            details = ", ".join(f"{key}={error[key]}" for key in ("code", "error_subcode", "type") if error.get(key))
            raise InstagramError(
                f"인스타 API가 요청을 거절했습니다 (HTTP {response.status_code}"
                f"{', ' + details if details else ''}). Instagram Login 토큰, 계정 ID와 권한을 확인해 주세요."
            )
        return payload

    def remaining(self):
        result = self.request("GET", f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")
        try:
            quota = result["data"][0]
            total = int(quota["config"]["quota_total"])
            return max(0, total - int(quota["quota_usage"])), total
        except (KeyError, IndexError, TypeError, ValueError):
            raise InstagramError("인스타 게시 한도를 확인하지 못했습니다. 계정 연결을 확인해 주세요.") from None

    def wait_ready(self, container_id):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            result = self.request("GET", container_id, timeout=min(15, max(0.1, remaining)), fields="status_code")
            if result.get("status_code") == "FINISHED":
                return
            if result.get("status_code") in {"ERROR", "EXPIRED"}:
                raise InstagramError("인스타에서 사진 처리를 완료하지 못했습니다. 사진을 확인한 뒤 재시도해 주세요.")
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        raise InstagramError("사진 처리 시간이 60초를 초과했습니다. 잠시 후 재시도해 주세요.")

    def create_container(self, urls, caption):
        if not 1 <= len(urls) <= 10:
            raise InstagramError("사진을 1~10장 선택해 주세요.")
        if len(urls) == 1:
            payload = self.request("POST", f"{self.user_id}/media", image_url=urls[0], caption=caption)
        else:
            children = []
            for url in urls:
                child = self.request("POST", f"{self.user_id}/media", image_url=url, is_carousel_item="true")
                child_id = self.require_id(child)
                self.wait_ready(child_id)
                children.append(child_id)
            payload = self.request("POST", f"{self.user_id}/media", media_type="CAROUSEL",
                                   children=",".join(children), caption=caption)
        container_id = self.require_id(payload)
        self.wait_ready(container_id)
        return container_id

    @staticmethod
    def require_id(payload):
        value = str(payload.get("id", ""))
        if not value.isdigit():
            raise InstagramError("인스타에서 게시물 번호를 받지 못했습니다.")
        return value

    def publish(self, container_id):
        payload = self.request("POST", f"{self.user_id}/media_publish", creation_id=container_id)
        try:
            return self.require_id(payload)
        except InstagramError:
            raise PublishUncertain("게시 요청은 전송했으나 결과 번호를 받지 못했습니다. 인스타 계정을 먼저 확인해 주세요.") from None

    def permalink(self, media_id):
        url = self.request("GET", media_id, fields="permalink").get("permalink", "")
        if not re.fullmatch(r"https://(?:www\.)?instagram\.com/[^\s]+", url):
            raise InstagramError("게시 완료 후 링크를 조회하지 못했습니다. 인스타 계정에서 확인해 주세요.")
        return url

    def test_connection(self):
        account = self.request("GET", self.user_id, fields="id,username")
        remaining, total = self.remaining()
        return f"인스타 @{account.get('username', '')} 연결 완료 · 남은 게시 한도 {remaining}/{total}"


def refresh_token(config, token):
    expiry = config.get("token_expires_at")
    if not expiry:
        raise InstagramError("설정에서 장기 토큰의 실제 만료일을 입력해 주세요.")
    try:
        expires = datetime.fromisoformat(expiry)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except ValueError:
        raise InstagramError("토큰 만료일 형식을 확인해 주세요.") from None
    if expires - datetime.now(timezone.utc) > timedelta(days=7):
        return token
    try:
        response = requests.get("https://graph.instagram.com/refresh_access_token",
                                params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        refreshed = payload["access_token"]
        duration = int(payload["expires_in"])
        if not isinstance(refreshed, str) or not refreshed or duration <= 0:
            raise ValueError
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise InstagramError("인스타 토큰 자동 갱신에 실패했습니다. 설정에서 새 장기 토큰으로 다시 연결해 주세요.") from None
    storage.save_secret("ig_token", refreshed)
    config["token_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat()
    storage.save_config(config)
    return refreshed


def configured_client(config):
    token = storage.get_secret("ig_token")
    if not token:
        raise InstagramError("설정에서 인스타 장기 액세스 토큰을 입력해 주세요.")
    return Instagram(config["ig_user_id"], refresh_token(config, token), config["graph_version"])


def configured_host(config):
    return Cloudinary(config["cloud_name"], storage.get_secret("cloud_api_key"), storage.get_secret("cloud_api_secret"))


def upload_post(product, paths, caption, progress=lambda message: None):
    validate_product(product)
    validate_caption(caption)
    if not 1 <= len(paths) <= 10:
        raise ValueError("사진을 1~10장 선택해 주세요.")
    record_id = storage.start_record(product, caption, paths)
    public_ids, warnings = [], []
    host, media_id, link = None, "", ""
    status, detail = "실패", ""
    publish_started = False
    try:
        config = storage.load_config()
        client = configured_client(config)
        remaining, total = client.remaining()
        progress(f"남은 게시 한도 {remaining}/{total} · 사진 준비 중")
        if remaining == 0:
            raise InstagramError(f"남은 게시 한도 0/{total}입니다. 한도가 회복된 뒤 다시 시도해 주세요.")
        host = configured_host(config)
        urls = []
        for index, path in enumerate(paths, 1):
            progress(f"사진 {index}/{len(paths)} 전처리 및 전송 중")
            # Same square canvas for a carousel prevents Instagram cropping later slides.
            jpeg = prepare_image(path, ratio=1 if len(paths) > 1 else None)
            public_id = f"insta-uploader/{uuid.uuid4().hex}"
            public_ids.append(public_id)  # Known before sending, including an upload timeout.
            urls.append(host.upload(jpeg, public_id))
        progress("인스타 사진 처리 대기 중")
        container_id = client.create_container(urls, caption)
        # Commit the uncertainty state BEFORE the irreversible network call.
        storage.update_record(record_id, "결과 확인 필요", detail=f"컨테이너 {container_id}")
        publish_started = True
        progress("인스타 게시 요청 중 — 창을 닫지 마세요")
        media_id = client.publish(container_id)
        status = "성공"
        storage.update_record(record_id, status, media_id=media_id)
        try:
            link = client.permalink(media_id)
        except InstagramError as error:
            warnings.append(str(error))
    except PublishUncertain:
        status = "결과 확인 필요"
        detail = "응답이 끊겨 게시 여부를 확정할 수 없습니다. 중복 게시를 피하려면 인스타 계정을 먼저 확인해 주세요."
    except ValueError as error:
        if media_id:
            status = "성공"
            warnings.append("게시에는 성공했으나 기록 또는 링크 처리에 문제가 있습니다.")
        else:
            status, detail = "실패", str(error)
    except Exception:
        status = "성공" if media_id else ("결과 확인 필요" if publish_started else "실패")
        detail = "처리를 완료하지 못했습니다. 기록과 인스타 계정을 확인해 주세요."
    finally:
        for public_id in public_ids:
            try:
                host.delete(public_id)
            except Exception:
                warnings.append(f"Cloudinary 임시 사진을 직접 삭제해 주세요: {public_id}")
        detail = "\n".join(filter(None, [detail, *warnings]))
        try:
            storage.update_record(record_id, status, media_id, link, detail)
        except Exception:
            detail += "\n기록 저장에 실패했습니다. 인스타에서 게시 여부를 확인해 주세요."
    return {"status": status, "media_id": media_id, "permalink": link, "detail": detail}
