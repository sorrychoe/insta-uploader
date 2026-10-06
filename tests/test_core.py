"""Offline checks: python -m unittest discover -s tests -v"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
import requests

import ai
import images
import instagram
import storage

PRODUCT = {"name": "한글 상품", "features": "가볍고 휴대하기 좋음", "tone": "친근", "store_link": ""}


class ImageTests(unittest.TestCase):
    def test_padding_transparency_and_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            for size in ((400, 1200), (2400, 400), (1441, 1800), (400, 400), (1, 30), (30, 1)):
                path = Path(directory) / "한글 사진.png"
                Image.new("RGBA", size, (255, 0, 0, 0)).save(path)
                data = images.prepare_image(path)
                with Image.open(BytesIO(data)) as result:
                    self.assertEqual(result.format, "JPEG")
                    self.assertEqual(result.mode, "RGB")
                    self.assertLessEqual(max(result.size), 1440)
                    self.assertTrue(0.8 <= result.width / result.height <= 1.91)
                    self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
                self.assertLessEqual(len(data), 8_000_000)
                with Image.open(path) as original:
                    self.assertEqual(original.size, size)

    def test_exif_rotation_and_carousel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "회전.jpg"
            source = Image.new("RGB", (100, 60), "red")
            exif = Image.Exif()
            exif[274] = 6
            source.save(path, exif=exif)
            with Image.open(BytesIO(images.prepare_image(path))) as result:
                self.assertGreater(result.height, result.width)
                self.assertNotIn(274, result.getexif())
            with Image.open(BytesIO(images.prepare_image(path, ratio=1))) as result:
                self.assertEqual(result.width, result.height)
                self.assertGreater(result.getpixel((result.width // 2, result.height // 2))[0], 240)

    def test_invalid_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.png"
            path.write_text("not an image")
            with self.assertRaises(ValueError):
                images.prepare_image(path)
            Image.new("RGB", (2, 2)).save(path, format="GIF")
            with self.assertRaises(ValueError):
                images.prepare_image(path)

    def test_host_signature_and_cleanup_errors(self):
        host = images.Cloudinary("demo", "api-key", "secret")
        with patch("images.time.time", return_value=123), patch("images.requests.post") as post:
            post.return_value.json.return_value = {"secure_url": "https://example.com/image.jpg"}
            self.assertTrue(host.upload(b"jpeg", "insta-uploader/one").startswith("https://"))
            data = post.call_args.kwargs["data"]
            expected = images.hashlib.sha1(b"public_id=insta-uploader/one&timestamp=123secret").hexdigest()
            self.assertEqual(data["signature"], expected)
            post.return_value.json.return_value = {"result": "error"}
            with self.assertRaises(ValueError):
                host.delete("one")


class CaptionTests(unittest.TestCase):
    def test_length_boundaries_and_body_tags(self):
        ai.validate_caption("가" * 2200)
        with self.assertRaises(ValueError):
            ai.validate_caption("가" * 2201)
        tags = [f"#태그{i}" for i in range(30)]
        ai.validate_caption(ai.assemble_caption("본문", tags))
        with self.assertRaises(ValueError):
            ai.validate_caption(ai.assemble_caption("본문 #추가", tags))
        self.assertEqual(ai.assemble_caption("  내용  ", "태그 #태그, #Brand #brand"), "내용\n\n#태그 #Brand")
        with self.assertRaises(ValueError):
            ai.parse_hashtags("#잘못된-태그")
        with self.assertRaises(ValueError):
            ai.validate_caption("   ")

    def test_generation_schema_fixed_tags_and_image(self):
        result = {"caption": "상품 소개", "hashtags": [f"#태그{i}" for i in range(25)]}
        message = SimpleNamespace(refusal=None, content=json.dumps(result))
        response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
        with patch("ai.OpenAI") as factory:
            client = factory.return_value.__enter__.return_value
            client.chat.completions.create.return_value = response
            generated = ai.generate({**PRODUCT, "store_link": "https://store.example"},
                                    {"model": "gpt-4.1-mini", "fixed_hashtags": " ".join(f"#브랜드{i}" for i in range(10))},
                                    "test-key", b"jpeg")
            self.assertEqual(len(generated["hashtags"]), 30)
            self.assertEqual(generated["hashtags"][0], "#브랜드0")
            self.assertTrue(generated["caption"].endswith("프로필 링크 확인"))
            sent = client.chat.completions.create.call_args.kwargs
            self.assertTrue(sent["response_format"]["json_schema"]["strict"])
            self.assertEqual(sent["messages"][1]["content"][1]["type"], "image_url")
            self.assertEqual(factory.call_args.kwargs["max_retries"], 0)

    def test_timeout_retries_three_times(self):
        import httpx
        error = ai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))
        with patch("ai.OpenAI") as factory, patch("ai.time.sleep") as sleep:
            create = factory.return_value.__enter__.return_value.chat.completions.create
            create.side_effect = error
            with self.assertRaisesRegex(ValueError, "OpenAI"):
                ai.generate(PRODUCT, {"model": "test"}, "test-key")
            self.assertEqual(create.call_count, 4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])


class StorageTests(unittest.TestCase):
    def test_config_allowlist_credentials_and_history(self):
        with tempfile.TemporaryDirectory() as directory, patch("storage.app_dir", return_value=Path(directory)):
            storage.save_config({**storage.DEFAULTS, "openai_key": "never-plain", "ig_token": "never-plain"})
            self.assertNotIn("never-plain", (Path(directory) / "config.json").read_text())
            with patch("storage.credential_store") as store:
                storage.save_secret("openai_key", "secret")
                store.return_value.set_password.assert_called_once_with("InstaUploader", "openai_key", "secret")
            record_id = storage.start_record(PRODUCT, "소개글", ["한글 경로.png"])
            storage.update_record(record_id, "성공", "123", "https://www.instagram.com/p/test/")
            record = storage.history()[0]
            self.assertEqual(record["status"], "성공")
            self.assertEqual(json.loads(record["product"]), PRODUCT)
            self.assertEqual(json.loads(record["images"]), ["한글 경로.png"])
            storage.write_json("draft.json", {"caption": "보존"})
            self.assertEqual(storage.read_json("draft.json", {})["caption"], "보존")

    def test_insecure_backend_rejected(self):
        with patch("storage.os.name", "posix"), patch("storage.keyring.get_keyring", return_value=object()):
            with self.assertRaises(ValueError):
                storage.save_secret("ig_token", "secret")

    def test_corrupt_config_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch("storage.app_dir", return_value=Path(directory)):
            path = Path(directory) / "config.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                storage.load_config()
            self.assertEqual(path.read_text(), "broken")


class InstagramTests(unittest.TestCase):
    def test_single_and_carousel_wait_for_every_container(self):
        client = instagram.Instagram("123", "secret")
        with patch.object(client, "request", side_effect=[{"id": "11"}]) as request, patch.object(client, "wait_ready") as wait:
            self.assertEqual(client.create_container(["https://a"], "caption"), "11")
            self.assertEqual(request.call_args.kwargs["caption"], "caption")
            wait.assert_called_once_with("11")
        with patch.object(client, "request", side_effect=[{"id": "11"}, {"id": "12"}, {"id": "13"}]) as request, patch.object(client, "wait_ready") as wait:
            self.assertEqual(client.create_container(["https://a", "https://b"], "caption"), "13")
            self.assertEqual([call.args[0] for call in wait.call_args_list], ["11", "12", "13"])
            self.assertEqual(request.call_args.kwargs["children"], "11,12")

    def test_container_error_timeout_and_dynamic_quota(self):
        client = instagram.Instagram("123", "secret")
        with patch.object(client, "request", return_value={"status_code": "ERROR"}):
            with self.assertRaises(instagram.InstagramError):
                client.wait_ready("1")
        with patch("instagram.time.monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(instagram.InstagramError, "60초"):
                client.wait_ready("1")
        with patch.object(client, "request", return_value={"data": [{"quota_usage": 42, "config": {"quota_total": 50}}]}):
            self.assertEqual(client.remaining(), (8, 50))

    def test_publish_transport_is_uncertain_and_secrets_not_shown(self):
        client = instagram.Instagram("123", "secret")
        with patch("instagram.requests.request", side_effect=requests.Timeout("token=secret")) as request:
            with self.assertRaises(instagram.PublishUncertain) as caught:
                client.publish("1")
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(request.call_count, 1)
        response = Mock(status_code=503)
        with patch("instagram.requests.request", return_value=response):
            with self.assertRaises(instagram.PublishUncertain):
                client.publish("1")

    def test_refresh_window(self):
        config = {**storage.DEFAULTS, "token_expires_at": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()}
        with patch("instagram.requests.get") as get:
            self.assertEqual(instagram.refresh_token(config, "old"), "old")
            get.assert_not_called()
        config["token_expires_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        with patch("instagram.requests.get") as get, patch("storage.save_secret") as secret, patch("storage.save_config") as save:
            get.return_value.json.return_value = {"access_token": "new", "expires_in": 5184000}
            self.assertEqual(instagram.refresh_token(config, "old"), "new")
            secret.assert_called_once_with("ig_token", "new")
            save.assert_called_once()
            self.assertNotIn("new", json.dumps(config))

    def test_upload_outcomes_cleanup_and_durable_intent(self):
        for outcome in ("success", "permalink_failure", "uncertain", "processing_failure", "upload_timeout", "cleanup_failure"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                with patch("storage.app_dir", return_value=Path(directory)), patch("instagram.configured_client") as factory, patch("instagram.configured_host") as hosting, patch("instagram.prepare_image", return_value=b"jpeg"):
                    client, host = factory.return_value, hosting.return_value
                    client.remaining.return_value = (99, 100)
                    client.create_container.return_value = "100"
                    client.permalink.return_value = "https://www.instagram.com/p/test/"
                    host.upload.return_value = "https://example.com/image.jpg"
                    def publish(container):
                        self.assertEqual(storage.history()[0]["status"], "결과 확인 필요")
                        if outcome == "uncertain":
                            raise instagram.PublishUncertain("응답 없음")
                        return "200"
                    client.publish.side_effect = publish
                    if outcome == "permalink_failure":
                        client.permalink.side_effect = instagram.InstagramError("링크 조회 실패")
                    if outcome == "processing_failure":
                        client.create_container.side_effect = instagram.InstagramError("사진 처리 실패")
                    if outcome == "upload_timeout":
                        host.upload.side_effect = ValueError("호스팅 연결 실패")
                    if outcome == "cleanup_failure":
                        host.delete.side_effect = ValueError("삭제 실패")
                    result = instagram.upload_post(PRODUCT, ["test.png"], "테스트 캡션")
                    expected = "결과 확인 필요" if outcome == "uncertain" else ("실패" if outcome in {"processing_failure", "upload_timeout"} else "성공")
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(storage.history()[0]["status"], expected)
                    host.delete.assert_called_once()
                    if outcome == "cleanup_failure":
                        self.assertIn("직접 삭제", result["detail"])
                    if outcome in {"processing_failure", "upload_timeout"}:
                        client.publish.assert_not_called()
                    else:
                        self.assertEqual(client.publish.call_count, 1)


if __name__ == "__main__":
    unittest.main()
