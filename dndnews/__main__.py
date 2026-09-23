"""실행 방법
  python -m dndnews edition     # 조간 제작·발행 (매일 04:00 KST)
  python -m dndnews breaking    # 속보란 갱신 (20분마다)
  python -m dndnews render      # 저장된 최신호로 사이트만 다시 생성
"""
import sys

from .common import DATA, load_config, read_json


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "edition"
    cfg = load_config()
    if cmd == "edition":
        from .breaking import update
        from .edition import build
        from .render import render_edition

        try:
            update(cfg)                  # 1면 속보 상자용으로 속보도 한 번 갱신
        except Exception as e:
            print("속보 갱신 실패(조간은 계속):", e)
        render_edition(cfg, build(cfg))
    elif cmd == "breaking":
        from .breaking import update
        from .render import render_breaking

        render_breaking(cfg, update(cfg))
    elif cmd == "render":
        from .render import render_edition

        ed = read_json(DATA / "latest.json", None)
        if not ed:
            print("저장된 신문이 없습니다. 먼저 edition을 실행하세요.")
            return 1
        render_edition(cfg, ed)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
