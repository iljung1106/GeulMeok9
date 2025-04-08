import google.generativeai as genai
import os

# AI 설정 값
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "300"))  # 기본 타임아웃 300초로 증가
AI_SAFETY_SETTINGS = os.getenv("AI_SAFETY_SETTINGS", "off")  # 기본 검열 수준을 off로 설정
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.7"))  # 기본 온도 설정
AI_TOP_P = float(os.getenv("AI_TOP_P", "0.9"))  # 기본 top_p 설정

# API 키 관리 (여러 개의 API 키 지원)
GOOGLE_API_KEYS = []
api_key_env = os.getenv("GOOGLE_API_KEY", "")
if api_key_env:
    # 쉼표로 구분된 API 키 목록을 배열로 변환
    GOOGLE_API_KEYS = [key.strip() for key in api_key_env.split(',') if key.strip()]
    print(f"로드된 API 키: {len(GOOGLE_API_KEYS)}개")
    for i, key in enumerate(GOOGLE_API_KEYS):
        print(f"  키 {i+1}: {key[:4]}...{key[-4:] if len(key) > 8 else ''} (길이: {len(key)})")

# 현재 사용할 API 키의 인덱스
CURRENT_API_KEY_INDEX = 0

# 유효하지 않은 API 키 목록
INVALID_API_KEYS = set()

# API 키 순환 함수
def get_next_api_key():
    global CURRENT_API_KEY_INDEX, INVALID_API_KEYS
    
    # API 키가 없는 경우
    if not GOOGLE_API_KEYS:
        print("API 키가 설정되지 않았습니다.")
        return None
    
    # 모든 API 키가 유효하지 않은 경우, 유효하지 않은 키 목록 초기화
    valid_keys = [key for key in GOOGLE_API_KEYS if key not in INVALID_API_KEYS]
    if not valid_keys:
        print("모든 API 키가 유효하지 않아 목록을 초기화합니다.")
        INVALID_API_KEYS.clear()
        valid_keys = GOOGLE_API_KEYS
    
    # 현재 인덱스가 범위를 벗어나면 재설정
    if CURRENT_API_KEY_INDEX >= len(GOOGLE_API_KEYS):
        CURRENT_API_KEY_INDEX = 0
    
    # 현재 API 키 가져오기
    api_key = GOOGLE_API_KEYS[CURRENT_API_KEY_INDEX]
    print(f"API 키 사용: 인덱스 {CURRENT_API_KEY_INDEX}, 키 길이: {len(api_key)}")
    
    # 다음 인덱스로 업데이트
    CURRENT_API_KEY_INDEX = (CURRENT_API_KEY_INDEX + 1) % len(GOOGLE_API_KEYS)
    
    return api_key

# Configure Google AI API
if GOOGLE_API_KEYS:
    # 첫 번째 API 키로 초기 구성
    genai.configure(api_key=GOOGLE_API_KEYS[0])
    print(f"초기 API 키 설정 완료: 길이 {len(GOOGLE_API_KEYS[0])}")
else:
    print("Warning: GOOGLE_API_KEY not found in environment variables")

# AI Helper functions
def get_available_models():
    return {
        "main": ["gemini-2.5-pro-exp-03-25", "gemini-2.5-pro-preview-03-25", "gemini-2.0-flash-thinking-exp-01-21", "gemini-2.0-flash"],
        "assistant": ["gemini-2.0-flash", "gemini-2.0-flash-thinking-exp-01-21"]
    }

def generate_ai_response(prompt, model_name="gemini-2.5-pro-exp-03-25"):
    global INVALID_API_KEYS
    
    try:
        # 다음 API 키 가져오기
        api_key = get_next_api_key()
        if not api_key:
            return "API 키가 설정되지 않았습니다. 설정 페이지에서 API 키를 입력해주세요."
        
        # 현재 요청에 대한 API 키 설정
        print(f"API 요청에 사용할 키: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''}")
        genai.configure(api_key=api_key)
        
        # 안전 설정 구성 - 모든 검열 카테고리에 대해 최소 제한 설정
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
        
        # AI 안전 설정 적용
        if AI_SAFETY_SETTINGS == "moderate":
            safety_settings = None  # 기본 안전 설정 사용
        
        try:
            # 모델 생성
            model = genai.GenerativeModel(
                model_name=model_name,
                safety_settings=safety_settings,
                generation_config={
                    "temperature": AI_TEMPERATURE,
                    "top_p": AI_TOP_P,
                    "max_output_tokens": 8192,
                }
            )
            
            # 응답 생성 (timeout 파라미터 제거)
            try:
                response = model.generate_content(prompt)
                return response.text
            except Exception as timeout_error:
                # 타임아웃 또는 다른 오류 발생 시 스트리밍 모드로 시도
                error_message = str(timeout_error)
                print(f"일반 요청 중 오류 발생: {error_message}, 스트리밍 모드로 재시도합니다.")
                
                # 스트리밍 모드로 시도 (일부 API에서 더 안정적)
                response = model.generate_content(prompt, stream=True)
                
                # 스트리밍 응답을 하나의 텍스트로 결합
                full_response = ""
                try:
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                except Exception as stream_error:
                    # 스트리밍 중 오류가 발생해도 지금까지 받은 내용 반환
                    print(f"스트리밍 중 오류 발생: {str(stream_error)}")
                    if full_response:
                        print(f"부분 응답 반환 (길이: {len(full_response)})")
                        return full_response + "\n\n[응답이 완전하지 않을 수 있습니다. 스트리밍 중 오류가 발생했습니다.]"
                    else:
                        raise stream_error  # 응답이 없으면 오류 발생
                
                return full_response
                
        except Exception as e:
            error_message = str(e)
            print(f"API 오류 발생: {error_message}")
            
            # API 키가 유효하지 않은 경우 해당 키를 유효하지 않은 목록에 추가
            if "API_KEY_INVALID" in error_message or "API key not valid" in error_message:
                INVALID_API_KEYS.add(api_key)
                print(f"유효하지 않은 API 키: {api_key[:4]}... - 다른 키로 재시도합니다.")
                
                # 다른 API 키로 재시도
                if len(GOOGLE_API_KEYS) > 1:
                    return generate_ai_response(prompt, model_name)
            
            return f"Error generating AI response: {error_message}"
    except Exception as e:
        error_message = str(e)
        print(f"일반 오류 발생: {error_message}")
        return f"Error generating AI response: {error_message}"

def check_spelling(text, model_name="gemini-2.0-flash"):
    prompt = f"""아래 텍스트의 맞춤법을 검사해주세요. 오류가 있다면 수정해서 전체 텍스트를 반환해주세요.
    오류가 없다면 '맞춤법 오류 없음'이라고 답변해주세요.
    
    텍스트:
    {text}"""
    
    return generate_ai_response(prompt, model_name)

def generate_summary(text, model_name="gemini-2.0-flash"):
    prompt = f"""다음 소설 회차의 내용을 사건과 인물 중심으로 300자 이내로 요약해주세요. 개인적인 감상이나 평가는 포함하지 마세요.:
    
    {text}"""
    
    return generate_ai_response(prompt, model_name)

def generate_major_summary(chapters, model_name="gemini-2.5-pro-exp-03-25"):
    # 모든 회차 내용을 결합
    combined_text = ""
    for i, chapter in enumerate(chapters):
        combined_text += f"회차 {i+1}: {chapter['title']}\n{chapter['content']}\n\n"
    
    prompt = f"""다음은 소설의 여러 회차 내용입니다. 이 내용을 바탕으로 전체 스토리의 대요약본을 작성해주세요.
    각 회차의 중요한 내용이 모두 포함되도록 하되, 전체적인 스토리 흐름을 파악할 수 있게 요약해주세요.
    
    {combined_text}"""
    
    return generate_ai_response(prompt, model_name)

def review_chapter(content, title, model_name="gemini-2.5-pro-exp-03-25"):
    """
    회차 내용에 대한 감평을 생성합니다.
    """
    prompt = f"""다음은 소설의 한 회차 내용입니다. 이 회차에 대한 감평을 작성해주세요.
    이 회차는 전체 소설의 일부분이며, 앞뒤 맥락이 잘려있을 수 있습니다. 이 점을 고려하여 감평해주세요.
    웹소설의 일부분임을 고려하고, 기본적으로 비판적인 태도를 유지하세요. 클리셰와 재미 요소를 언제나 생각하세요.
    
    회차 제목: {title}
    
    회차 내용:
    {content}
    
    이 회차만으로 평가하기 어려운 부분(전체 플롯, 캐릭터 아크 등)은 언급하지 않아도 됩니다.
    """
    
    return generate_ai_response(prompt, model_name)

def test_api_keys(api_keys_input):
    """
    API 키 목록을 테스트하고 결과를 반환합니다.
    """
    # API 키 목록 처리
    api_keys_list = []
    for key in api_keys_input.split(','):
        key = key.strip()
        if key:  # 빈 문자열이 아닌 경우에만 추가
            api_keys_list.append(key)
    
    if not api_keys_list:
        return {
            'success': False,
            'message': 'API 키가 입력되지 않았습니다.'
        }
    
    # 각 API 키 테스트
    valid_keys = []
    invalid_keys = []
    
    for i, api_key in enumerate(api_keys_list):
        try:
            # API 키 설정
            genai.configure(api_key=api_key)
            
            # 간단한 테스트 요청
            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content("Hello, API test.")
            
            # 응답이 성공적으로 생성되면 유효한 키로 간주
            valid_keys.append(api_key)
            print(f"API 키 테스트 성공: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''}")
        except Exception as e:
            error_message = str(e)
            invalid_keys.append({
                'key': api_key,
                'error': error_message
            })
            print(f"API 키 테스트 실패: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''} - {error_message}")
    
    # 테스트 결과 반환
    if valid_keys:
        # 테스트 후 원래 설정으로 복원
        if GOOGLE_API_KEYS:
            genai.configure(api_key=GOOGLE_API_KEYS[0])
            
        return {
            'success': True,
            'message': f'{len(valid_keys)}개의 API 키가 유효합니다. {len(invalid_keys)}개의 API 키가 유효하지 않습니다.',
            'valid_count': len(valid_keys),
            'invalid_count': len(invalid_keys)
        }
    else:
        return {
            'success': False,
            'message': f'모든 API 키({len(api_keys_list)}개)가 유효하지 않습니다. 첫 번째 오류: {invalid_keys[0]["error"] if invalid_keys else "알 수 없는 오류"}',
            'errors': [item['error'] for item in invalid_keys]
        }

def update_api_keys(new_api_keys):
    """
    API 키를 업데이트하고 결과를 반환합니다.
    """
    global GOOGLE_API_KEYS, CURRENT_API_KEY_INDEX, INVALID_API_KEYS
    
    # 쉼표로 구분된 API 키 목록을 배열로 변환 (공백 제거 및 빈 키 필터링)
    new_api_keys_list = []
    for key in new_api_keys.split(','):
        key = key.strip()
        if key:  # 빈 문자열이 아닌 경우에만 추가
            new_api_keys_list.append(key)
    
    print(f"새로운 API 키 목록: {len(new_api_keys_list)}개")
    for i, key in enumerate(new_api_keys_list):
        print(f"  키 {i+1}: {key[:4]}...{key[-4:] if len(key) > 8 else ''} (길이: {len(key)})")
    
    # 환경 변수 설정 (쉼표로 구분된 문자열로 저장)
    os.environ['GOOGLE_API_KEY'] = ','.join(new_api_keys_list)
    print(f"환경 변수에 저장된 API 키: {len(new_api_keys_list)}개")
    
    # 전역 변수 업데이트
    GOOGLE_API_KEYS = new_api_keys_list
    # API 키 인덱스 초기화
    CURRENT_API_KEY_INDEX = 0
    # 유효하지 않은 API 키 목록 초기화
    INVALID_API_KEYS.clear()
    
    if GOOGLE_API_KEYS:
        # 첫 번째 API 키로 초기 구성
        genai.configure(api_key=GOOGLE_API_KEYS[0])
        print(f"API 키 {len(GOOGLE_API_KEYS)}개로 업데이트 완료")
        return True, f'{len(GOOGLE_API_KEYS)}개의 Google API 키가 성공적으로 업데이트되었습니다.'
    else:
        return False, 'API 키가 설정되지 않았습니다.'
