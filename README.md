# 인스타 업로더

[`Agents.md`](Agents.md) 기획서의 1차 범위를 구현한 Windows용 Python 데스크톱 프로그램입니다.
사진 선택 → 제품 정보 입력 → AI 소개글 생성 → 확인·수정 → 인스타그램 게시 순서로 사용합니다.

## 실행

Windows 사용자는 GitHub 저장소의 **Releases**에서 `InstaUploader.exe`를 내려받아 실행합니다. Python 설치나 터미널 빌드는 필요하지 않습니다.

Linux 개발 환경에서는 Python 3.12와 GNU Make를 설치한 뒤 실행합니다.

```sh
make install
make run
```

## 최초 설정

1. 인스타그램 계정을 비즈니스 또는 크리에이터로 전환합니다.
2. [Meta 개발자 콘솔](https://developers.facebook.com/)에서 Instagram 제품을 사용하는 앱을 만들고 본인 계정을 연결합니다. **Instagram API with Instagram Login** 방식입니다. Facebook Login 토큰과 혼용하지 마세요.
3. `instagram_business_basic`, `instagram_business_content_publish` 권한의 **장기 액세스 토큰**, 인스타 계정 ID, 실제 만료일을 확인합니다. 새로 발급한 장기 토큰을 직접 입력하는 방식이며 앱 내부 OAuth 로그인은 제공하지 않습니다. 토큰의 만료일 입력 기본값은 오늘부터 60일이므로 이미 사용하던 토큰은 반드시 실제 날짜로 고칩니다.
4. [OpenAI](https://platform.openai.com/api-keys)에서 API 키를 만들고 API 결제를 설정합니다. 기본 모델은 `gpt-4.1-mini`이며 설정에서 Structured Outputs 및 필요 시 이미지 입력을 지원하는 모델로 바꿀 수 있습니다.
5. [Cloudinary](https://console.cloudinary.com/)에서 cloud name, API key, API secret을 확인합니다.
6. 앱의 **설정** 탭에 입력하고 **저장 후 연결 테스트**를 누릅니다. 비밀값 입력칸을 비워 두면 기존 값을 유지합니다. 연결 테스트는 OpenAI 모델 접근, 인스타 계정·게시 한도, Cloudinary 테스트 사진 업로드·삭제를 검사합니다. OpenAI 생성 잔액은 실제 생성 시 확인됩니다.

Meta 앱 역할·테스터 설정과 사용 권한은 계정에 맞게 설정해야 합니다. 다른 사람의 계정까지 지원하는 배포는 Meta의 앱 검토 요건을 확인하세요.

## 사용

- JPG/PNG 사진을 1~10장 선택하거나 끌어 놓습니다. 드래그 또는 위로/아래로 버튼으로 순서를 바꾸고 선택 삭제할 수 있습니다.
- 제품명과 핵심 특징은 필수입니다. 가격, 타깃, 스토어 링크, 추가 요청은 선택 사항입니다.
- **생성** 또는 **다시 생성**을 누릅니다. 사진 참고 체크 시 첫 사진을 OpenAI에 전송하며 추가 비용이 발생할 수 있습니다.
- 소개글·해시태그를 직접 수정합니다. 본문에 들어간 해시태그도 개수에 포함됩니다. 2,200자/30개를 넘으면 게시할 수 없습니다. 실제 계정/API가 더 엄격한 제한을 반환하면 태그를 줄여 주세요.
- 선택 사진의 전처리 결과를 미리 볼 수 있습니다. **업로드**를 누르면 최종 글과 사진 장수를 확인하고 **게시하기**로 확정합니다.
- 게시 성공 시 링크를 열 수 있습니다. **기록**에서 결과·오류·제품 정보를 확인하고 이전 제품을 불러올 수 있습니다.

원본 사진은 수정하지 않습니다. EXIF 회전을 반영하고 투명 배경과 비율 초과 부분을 흰 여백으로 처리하며 긴 변 1,440px, JPEG 8MB 이하로 변환합니다. 캐러셀은 뒤 사진이 잘리는 것을 방지하기 위해 모두 정사각 흰 여백을 사용합니다.

## 저장과 복구

- 일반 설정: `%APPDATA%\InstaUploader\config.json`
- 작성 중 내용: 같은 폴더의 `draft.json` (자동 저장, 앱 재실행 시 복원)
- 게시 기록: 같은 폴더의 `history.sqlite3`
- API 키·토큰: **Windows 자격 증명 관리자**, 서비스 이름 `InstaUploader`. 평문 저장소로 대체하지 않습니다.

사진은 경로만 기록하므로 원본을 옮기거나 삭제하면 다시 선택해야 합니다. 앱 실행 중 토큰을 매시간 확인하고 게시 전에도 확인해 만료 7일 이내이면 갱신합니다. 앱이 장기간 꺼져 있어 토큰이 만료되면 새 토큰을 입력해야 합니다.

게시 요청은 자동 재시도하지 않습니다. 응답이 끊기면 **결과 확인 필요**로 기록합니다. 인스타 계정을 먼저 확인한 뒤 재시도하세요. 게시 성공 후 링크 조회만 실패한 경우에는 성공 상태와 게시물 ID를 유지합니다. 앱이 강제 종료되면 준비 중 또는 결과 확인 필요 상태가 남을 수 있습니다.

전송한 Cloudinary 임시 사진은 성공·실패 후 모두 삭제를 시도합니다. 삭제 통신이 실패하면 기록에 삭제할 public ID가 표시됩니다. 앱 강제 종료 시에도 Cloudinary의 `insta-uploader/` 경로를 확인하고 남은 사진을 정리할 수 있습니다.

## 테스트

외부 계정·네트워크 없이 이미지 처리, 캡션 제한, JSON Schema 요청, 백오프, 보안 저장, 토큰 갱신, 캐러셀 순서, 게시 결과 불확실성과 정리를 검사합니다. `make install` 후 실행합니다.

```sh
make test
```

## Windows exe: GitHub Actions

`main` 브랜치에 푸시하거나 `main` 대상 PR을 열면 `.github/workflows/build.yml`이 Windows x64 / Python 3.12에서 의존성 설치 → 테스트 → PyInstaller 빌드를 수행합니다. 다른 브랜치(예: `master`) 푸시는 실행되지 않으므로 기본 브랜치를 `main`으로 사용하세요.

푸시 빌드가 성공하면 **Releases**에 `Build 실행번호.시도번호` 릴리스가 생성되고 `InstaUploader.exe`가 첨부됩니다. 태그는 `build-실행ID-시도번호`이며 실제 빌드 커밋을 가리킵니다. 재실행도 별도 릴리스로 보관합니다. PR 실행은 릴리스를 게시하지 않고 테스트·빌드와 아티팩트 업로드까지만 수행합니다.

모든 실행의 파일은 **Artifacts → InstaUploader-Windows-x64**에서도 14일간 내려받을 수 있습니다. 릴리스 게시에는 자동 제공되는 `GITHUB_TOKEN`의 `contents: write` 권한을 사용하므로 별도 토큰 설정은 필요하지 않습니다. 워크플로 파일을 저장소에 커밋·푸시해야 GitHub에서 실행됩니다. Windows 로컬 빌드 스크립트는 사용하지 않습니다.

코드 서명은 포함하지 않았습니다. 실제 배포 전에 Windows 10/11에서 실행·한글 경로·자격 증명 저장과 실제 계정의 단일/캐러셀 게시를 확인하세요.

## Linux 빌드와 Makefile

```sh
make help
make install
make test
make run
make build
./dist/InstaUploader
make clean
```

`make clean`은 프로젝트의 `__pycache__`, `.pyc`, `.pyo`와 PyInstaller 산출물 `build/`, `dist/`를 삭제합니다. `.venv`, `.git`은 유지합니다.

`make install`은 `.venv`를 만들고 의존성을 설치합니다. `run`, `test`, `build`는 이 가상환경을 사용합니다. `make build`는 테스트 성공 후 **Linux 실행 파일** `dist/InstaUploader`를 생성합니다. Windows exe는 위 GitHub Actions에서 생성합니다. Python 경로는 `make install PYTHON=/path/to/python3.12`처럼 지정할 수 있습니다.

Linux GUI 실행에는 Qt가 사용할 수 있는 데스크톱 환경이 필요합니다. 비밀값 저장에는 Secret Service 또는 KWallet 보안 저장소가 필요하며, 평문 저장소로 대체하지 않습니다. 배포 대상은 기획서대로 Windows이며 Linux 빌드는 개발·확인용입니다.

현재 검증: `make test`로 핵심 테스트 15개 통과, Make 명령과 워크플로 YAML 구성 확인. 현재 환경에서 PySide6/PyInstaller 설치가 되지 않아 실제 Linux 패키징, GitHub Actions의 Windows 빌드, GUI 및 외부 API 호출은 검증하지 않았습니다.

워크플로에서 사용하는 도구의 공식 문서: [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), [upload-artifact](https://github.com/actions/upload-artifact), [gh release create](https://cli.github.com/manual/gh_release_create).

## API 참고 자료

- [OpenAI 공식 Chat Completions 문서](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create): `response_format`의 strict JSON Schema 사용.
- [OpenAI GPT-4.1 mini 문서](https://developers.openai.com/api/docs/models/gpt-4.1-mini): 설정의 기본 모델.
- [Meta 공식 Instagram API 컬렉션](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api), [콘텐츠 게시 가이드](https://developers.facebook.com/docs/instagram-platform/content-publishing/): Instagram Login 호스트 `graph.instagram.com`을 사용합니다. 기본 API 버전은 `v24.0`이며 설정에서 변경할 수 있습니다. 게시 한도는 상수 대신 `content_publishing_limit` 응답을 확인합니다. 구현 중 Meta 개발자 문서의 일부는 로그인/429로 열리지 않아 실제 계정 검증이 필요합니다.
- [Cloudinary 서명 문서](https://cloudinary.com/documentation/authentication_signatures): 서명된 업로드·삭제 요청.

예약 게시, 스마트스토어 연동, 다중 계정, 릴스·스토리, 댓글 관리는 기획서의 2차 범위로 포함하지 않았습니다.

## 라이선스

[MIT License](LICENSE)
