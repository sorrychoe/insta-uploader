# 인스타 업로더

네이버 스마트스토어 사장님이 자사 제품을 인스타그램에 쉽게 올릴 수 있도록 돕는 Windows 데스크톱 프로그램입니다.

## 주요 기능

- **사진 업로드**: JPG/PNG 1~10장 선택 (2장 이상은 캐러셀), 인스타 규격에 맞게 자동 변환
- **AI 글 작성**: 제품 정보를 입력하면 OpenAI가 소개글과 해시태그를 생성, 직접 수정 가능
- **인스타 게시**: 공식 Instagram API로 바로 게시하고 게시물 링크 확인
- **게시 기록**: 지난 게시 내역 확인 및 이전 제품 정보 재사용

## 사용 흐름

사진 선택 → 제품 정보 입력 → AI 소개글·해시태그 생성 → 확인·수정 → 업로드

## 시작하기

[Releases](../../releases)에서 `InstaUploader.exe`를 내려받아 실행합니다. 사용하려면 아래 계정이 필요합니다.

- 인스타그램 비즈니스/크리에이터 계정과 Meta 개발자 앱의 장기 액세스 토큰
- OpenAI API 키
- Cloudinary 계정 (게시용 임시 이미지 호스팅)

API 키와 토큰은 Windows 자격 증명 관리자에 안전하게 저장됩니다. 계정 준비부터 게시, 문제 해결까지는 [설정 가이드](docs/setup.md)를 참고하세요.

소개글 생성은 OpenAI API 키만으로 사용할 수 있습니다. OpenAI·인스타·Cloudinary의 저장 및 연결 테스트 버튼은 각각 해당 서비스 설정만 저장하고 검사합니다. 다른 서비스의 입력값이나 연결 상태는 영향을 주지 않습니다. 인스타·Cloudinary 설정은 실제 게시할 때 필요하며, 로컬 SQLite DB에는 별도 키가 필요하지 않습니다.

## 기술 스택

Python 3.12 · PySide6 · Pillow · OpenAI API · Instagram Graph API · Cloudinary · PyInstaller

## 개발

```sh
make install   # 가상환경 생성 및 의존성 설치
make run       # 실행
make test      # 테스트
```

Windows exe는 `main` 브랜치에 푸시하면 GitHub Actions가 빌드해 Releases에 올립니다. 상세 기획은 [AGENTS.md](AGENTS.md)를 참고하세요.

## 라이선스

[MIT License](LICENSE)
