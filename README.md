# DnD News — 자동 발행 신문

매일 04:00(KST)에 국내외 뉴스를 모아 06:00 전에 조간을 발행하고, 20분마다 속보란을 갱신하는 프로그램입니다.
서버 없이 **GitHub(무료) + Claude API**로 돌아가며, 결과는 내 도메인의 웹사이트로 공개됩니다.

## 어떻게 만들어지나

| 단계 | 하는 일 | 신뢰성 장치 |
|---|---|---|
| 1. 수집 | 언론사·공식기관 RSS 약 50개에서 최근 26시간 기사 수집 | 사람 기자가 쓰는 언론사·공식기관만. 구글 뉴스 결과는 `trusted_outlets` 목록에 있는 매체만 사용 |
| 2. 편집회의 | Claude가 같은 사건 기사를 묶고 중요도 판단 | 주어진 기사 id만 쓰게 하고 코드가 다시 확인 |
| 3. 교차검증 | 서로 다른 언론사 2곳 이상 보도한 스토리만 통과 | 공식기관 1차 발표만 예외. 계열사(연합뉴스·연합뉴스TV 등)는 한 곳으로 셈 |
| 4. 작성 | 원문 본문만 근거로 한국어 기사 작성 | 근거 밖 사실·수치·전망 금지, 투자권유 금지, 문단마다 출처 번호 |
| 5. 사실확인 | 다른 호출이 제목~본문 문장을 원문과 하나씩 대조 | 근거 없는 문장 삭제. 제목이 근거 없거나 25% 넘게 지워지면 기사 폐기 |
| 6. 배치 | 중요도·보도 매체 수·신뢰 등급으로 1~20위 배치 | 기사마다 근거 원문 링크와 보도 매체 목록 공개 |
| 시세 | 지수·환율·금리·원자재·코인·수급 | AI가 아니라 데이터 API 값 그대로. 못 가져오면 "—" |
| 속보 | 20분마다 속보 피드 수집, 해외 제목은 번역 + 원문 병기 | 기사를 새로 쓰지 않고 원 언론사 제목과 링크만 |

## 설치 (처음 한 번, 약 30분)

1. **GitHub 저장소 만들기** — 이 폴더 전체를 새 저장소에 올립니다.
   저장소를 **Public**으로 두면 GitHub Actions 사용 시간이 무제한 무료입니다. (Private은 월 2,000분 한도라 속보 20분 주기를 돌리면 모자랍니다.)
2. **비밀값 등록** — 저장소 Settings → Secrets and variables → Actions → New repository secret
   - `ANTHROPIC_API_KEY` : console.anthropic.com 에서 발급 (필수)
   - `KRX_ID`, `KRX_PW` : 한국거래소 정보데이터시스템(data.krx.co.kr) 회원 계정 (외국인·기관 순매수 표시용, 선택)
3. **웹사이트 켜기** — Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, 폴더: `/docs` → Save
4. **내 도메인 연결**
   - `config.yaml`의 `site.url`을 내 도메인으로 바꿉니다 (예: `https://news.mydomain.com`)
   - 도메인 업체 DNS에 `CNAME` 레코드 추가: `news` → `<GitHub아이디>.github.io`
   - Settings → Pages → Custom domain에 도메인 입력 → *Enforce HTTPS* 체크
5. **첫 발행 시험** — Actions 탭 → "조간 발행" → Run workflow. 약 10~20분 뒤 사이트에 신문이 뜹니다.

이후에는 매일 04:00에 자동으로 제작이 시작됩니다. GitHub 예약 실행은 가끔 늦어질 수 있어 04:40에 예비 실행이 한 번 더 걸려 있고, 이미 발행됐으면 건너뜁니다.

## 자주 바꾸는 설정 (`config.yaml`)

- 신문 이름·슬로건: `site.name`, `site.tagline`
- 기사 수: `edition.articles` (기본 20)
- 교차검증 기준: `edition.min_outlets` (기본 2곳, 3으로 올리면 더 엄격)
- 06:00 정각에 맞춰 공개: `edition.hold_until: "06:00"`
- 출처 추가·삭제: `feeds`, 구글 뉴스 허용 매체: `trusted_outlets`
- 속보 인물 태그: `people`
- 사용 모델: `models`

## 비용 (대략적인 추정)

- Claude API: 조간 하루 약 2달러, 속보 하루 약 1달러 안팎 → **월 70~100달러 수준**. 실제 금액은 기사 길이와 뉴스량에 따라 달라지니 첫 주에 console.anthropic.com 사용량을 확인하세요.
- GitHub Pages·Actions: Public 저장소면 무료. 도메인 비용만 별도.

## 내 컴퓨터에서 돌려보기

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # 없으면 '시험 운행판'(헤드라인만)으로 만들어짐
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

- 원문 기사의 저작권은 각 언론사에 있습니다. 이 프로그램은 원문을 옮겨 싣지 않고 새로 작성하며 출처를 밝히지만, 상업적으로 운영할 계획이면 뉴스 이용 약관과 저작권 문제를 전문가와 확인하세요.
- AI 사실확인은 사람 데스크를 대신하지 못합니다. 처음 몇 주는 매일 아침 1면 기사 몇 개를 원문과 직접 대조해 보시길 권합니다.
- 피드 주소는 언론사 사정으로 바뀔 수 있습니다. Actions 실행 기록에 "피드 실패"가 반복되면 해당 주소를 고치거나 뺍니다.
