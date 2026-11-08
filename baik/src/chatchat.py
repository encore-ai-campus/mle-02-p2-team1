import sys
import json
import requests

# 1. 환경 설정 (본인의 API Key를 입력하세요)
API_KEY = "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"
URL = "https://openai.com"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 대화 기록을 보관할 리스트
conversation_history = []

print("==================================================")
print("🤖 GPT-6.1 Terra (High 추론) 챗봇 연결 완료")
print("👉 종료하려면 '종료' 또는 'exit'를 입력하세요.")
print("==================================================")

while True:
    # 2. 사용자 입력 받기
    user_input = input("\n👤 유저: ")
    if user_input.strip() in ["종료", "exit", "quit", "q"]:
        print("🤖 챗봇을 종료합니다.")
        break
        
    if not user_input.strip():
        continue

    # 대화 기록에 사용자 입력 추가
    conversation_history.append({"role": "user", "content": user_input})

    # 3. GPT-6.1 Terra / Responses API 규격 페이로드 구성
    # payload = {
    #     "model": "gpt-6.1-terra",
    #     "input": conversation_history,  # 누적된 대화 기록 전달
    #     "reasoning": {
    #         "effort": "high"          # High 추론 수준 고정
    #     },
    #     "stream": True                 # 실시간 타이핑 효과 활성화
    # }
        # 임시 검증을 위해 누구나 접근 가능한 기본 모델 ID로 교체 테스트
    payload = {
        "model": "gpt-4o",  # gpt-6.1-terra 대신 교체하여 테스트
        "input": conversation_history,
        "stream": True
    }


    print("🤖 테라 (생각하는 중...): ", end="", flush=True)

    try:
        # 4. API 서버에 스트리밍 요청 전송
        response = requests.post(URL, json=payload, headers=headers, stream=True)
        
        # 만약 연결 오류가 발생하면 에러 코드를 확인하기 위함
        if response.status_code != 200:
            print(f"\n❌ 에러 발생 (상태 코드: {response.status_code})")
            print(f"상세 내용: {response.text}")
            continue

        assistant_reply = ""

        # 5. 스트리밍 데이터 한 줄씩 읽어서 실시간 출력
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8').strip()
                
                # SSE(Server-Sent Events) 데이터 포맷 파싱
                if decoded_line.startswith("data:"):
                    data_str = decoded_line[5:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data_json = json.loads(data_str)
                        
                        # Responses API의 스트리밍 텍스트 추출 필드 작동
                        # 만약 타겟 서버가 구형 구조라면 data_json['choices'][0]['delta']['content']로 우회 시도
                        content = ""
                        if "choices" in data_json:
                            content = data_json["choices"][0].get("delta", {}).get("content", "")
                        elif "delta" in data_json:
                            content = data_json["delta"].get("text", "")
                        elif "output_text" in data_json:
                            content = data_json["output_text"]
                            
                        if content:
                            print(content, end="", flush=True)
                            assistant_reply += content
                            
                    except json.JSONDecodeError:
                        continue
                        
        print() # 답변 종료 후 줄바꿈
        
        # 챗봇의 답변도 대화 기록에 누적하여 문맥 기억 기능 구현
        if assistant_reply:
            conversation_history.append({"role": "assistant", "content": assistant_reply})

    except requests.exceptions.RequestException as e:
        print(f"\n❌ 네트워크 연결 실패: {e}")
