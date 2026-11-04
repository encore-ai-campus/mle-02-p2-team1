# 회의 대시보드

프로젝트 루트에서 `.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory dashboard`를 실행하고 브라우저에서 `http://localhost:8765`를 연다. 화면은 `meeting.json`을 10초마다 새로 읽는다. 에이전트의 내부 대화를 자동으로 수집하는 실시간 시스템이 아니라 진행자가 실제로 받은 결과를 파일에 반영하는 기록 기반 화면이다. 회의가 진행될 때 이 파일과 `src/docs/idea-lab/`의 회의록·대장을 함께 갱신한다.
