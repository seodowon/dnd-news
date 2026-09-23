# DnD News — 자동 발행 신문

매일 04:00(KST)에 국내외 뉴스를 모아 06:00 전에 조간을 발행하고, 20분마다 속보란을 갱신하는 프로그램입니다.
서버 없이 **GitHub(무료)** 로 돌아가며, 결과는 무료 웹사이트(GitHub Pages)로 공개됩니다.

## 지금 운영 방식: 무료 헤드라인판

비용 없이 운영하기 위해 **AI 기사 작성 단계를 끄고** 운영합니다 (API 키를 넣지 않으면 자동으로 이 방식).

| 단계 | 하는 일 |
|---|---|
| 수집 | 언론사·공식기관 RSS 약 50개에서 최근 26시간 보도 수집. 구글 뉴스 결과는 `trusted_outlets` 허용 매체만 |
| 교차확인 | 같은 사건을 다룬 제목끼리 묶고, 서로 다른 언론사 2곳 이상이 보도한 소식만 통과 (계열사는 한 곳, 공식기관 발표는 예외) |
| 배치 | 보도 매체 수·통신사/공식기관 여부·국내 보도 여부로 중요도 순 20개 |
| 게재 | 새 문장을 쓰지 않고 원 언론사 제목 + 원문 링크 + 보도 매체 목록 |
| 시세 | 지수·환율·금리·원자재·코인은 데이터 API 값 그대로, 못 가져오면 "—" |
| 속보 | 20분마다 원 언론사 제목과 링크 그대로 (해외 기사는 영어 제목 그대로) |

나중에 AI 기사 작성을 켜고 싶으면 GitHub Secrets에 `ANTHROPIC_API_KEY`를 넣기만 하면 됩니다(유료, 월 70~100달러 추정).

## 비용

- GitHub Pages + GitHub Actions: **공개(Public) 저장소면 무료** (비공개면 Actions 월 2,000분 한도라 속보 20분 주기에 모자람)
- 도메인: 기본 주소 `아이디.github.io/dnd-news`는 무료. 내 도메인을 쓰려면 도메인 구입 비용만

## 설치

1. 이 폴더를 GitHub 공개 저장소 `dnd-news`로 올립니다.
2. Settings → Pages → Source: *Deploy from a branch*, Branch `main`, 폴더 `/docs` → Save
3. Actions 탭에서 워크플로 사용을 허용하고, "조간 발행" → Run workflow로 첫 발행
4. (선택) 한국거래소 수급을 보이려면 Secrets에 `KRX_ID`, `KRX_PW` 등록
5. (선택) 내 도메인: `config.yaml`의 `site.url` 변경 → DNS에 CNAME `news` → `아이디.github.io` → Pages의 Custom domain 입력

## 자주 바꾸는 설정 (`config.yaml`)

- 신문 이름·슬로건: `site.name`, `site.tagline`
- 기사 수: `edition.articles` (기본 20)
- 교차검증 기준: `edition.min_outlets` (기본 2곳, 3으로 올리면 더 엄격)
- 06:00 정각에 맞춰 공개: `edition.hold_until: "06:00"`
- 출처 추가·삭제: `feeds`, 구글 뉴스 허용 매체: `trusted_outlets`
- 속보 인물 태그: `people`
- 사용 모델: `models`

## 내 컴퓨터에서 돌려보기

```bash
pip install -r requirements.txt
python -m dndnews edition                 # 조간
python -m dndnews breaking                # 속보
python -m http.server -d docs 8000        # http://localhost:8000 에서 확인
```

## 폴더 구조

```
config.yaml            설정 (출처·분량·모델)
dndnews/               프로그램
  collect.py           RSS 수집, 신뢰 매체 필터
  cluster.py           스토리 묶기·교차검증·순위
  sources.py           원문 본문 확보
  write.py             기사 작성 + 문장 단위 사실확인
  market.py            시세·수급 데이터
  breaking.py          속보란
  render.py            웹페이지 생성
templates/, static/    디자인
data/                  발행 기록 (날짜별 JSON)
docs/                  공개되는 웹사이트
.github/workflows/     자동 실행 일정
```

## 운영하면서 꼭 챙길 것

- 원문 기사의 저작권은 각 언론사에 있습니다. 이 프로그램은 제목과 링크만 싣고 본문을 옮기지 않지만, 상업적으로 운영할 계획이면 뉴스 이용 약관과 저작권 문제를 전문가와 확인하세요.
- 제목 유사도로 같은 사건을 묶기 때문에 가끔 다른 사건이 한 묶음에 섞이거나, 같은 사건이 두 번 실릴 수 있습니다. 처음 몇 주는 아침마다 1면을 훑어보시길 권합니다.
- 피드 주소는 언론사 사정으로 바뀔 수 있습니다. Actions 실행 기록에 "피드 실패"가 반복되면 해당 주소를 고치거나 뺍니다.
