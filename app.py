import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
import markdown
import json
import sys
import jinja2

# UTF-8 인코딩 설정
if sys.platform.startswith('win'):
    import locale
    locale.setlocale(locale.LC_ALL, 'Korean_Korea.utf8')

# Load environment variables
load_dotenv()

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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'  # Add secret key for session
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///geulmeok9.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 한글 처리를 위한 JSON 인코딩 설정
app.config['JSON_AS_ASCII'] = False

# nl2br 필터 추가
@app.template_filter('nl2br')
def nl2br_filter(text):
    if text:
        return jinja2.utils.markupsafe.Markup(text.replace('\n', '<br>'))
    return ''

db = SQLAlchemy(app)

# Database Models
class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    chapters = db.relationship('Chapter', backref='novel', lazy=True, cascade="all, delete-orphan")
    characters = db.relationship('Character', backref='novel', lazy=True, cascade="all, delete-orphan")
    settings = db.relationship('Setting', backref='novel', lazy=True, cascade="all, delete-orphan")
    prompts = db.relationship('Prompt', backref='novel', lazy=True, cascade="all, delete-orphan")
    major_summaries = db.relationship('MajorSummary', backref='novel', lazy=True, cascade="all, delete-orphan")

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)

class MajorSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    chapter_range = db.Column(db.String(200))  # 요약에 포함된 회차 ID들을 저장 (예: "1,2,3,5,8")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Character(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Prompt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=True)
    prompt_type = db.Column(db.String(50), nullable=False)  # system, top, bottom
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)

# AI Helper functions
def get_available_models():
    return {
        "main": ["gemini-2.5-pro-preview-03-25", "gemini-2.0-flash-thinking-exp-01-21", "gemini-2.0-flash"],
        "assistant": ["gemini-2.0-flash", "gemini-2.0-flash-thinking-exp-01-21"]
    }

def generate_ai_response(prompt, model_name="gemini-2.5-pro-preview-03-25"):
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
            
            # 응답 생성 (타임아웃 설정)
            response = model.generate_content(prompt, timeout=AI_TIMEOUT)
            return response.text
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
            
            # 타임아웃 오류 발생 시 재시도
            if "504 Deadline Exceeded" in error_message or "timeout" in error_message.lower():
                print("타임아웃 오류 발생, 스트리밍 모드로 재시도합니다.")
                try:
                    # 스트리밍 모드로 시도 (일부 API에서 더 안정적)
                    response = model.generate_content(prompt, stream=True)
                    # 스트리밍 응답을 하나의 텍스트로 결합
                    full_response = ""
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                    return full_response
                except Exception as retry_error:
                    retry_error_message = str(retry_error)
                    print(f"스트리밍 재시도 중 오류: {retry_error_message}")
                    
                    # API 키가 유효하지 않은 경우 해당 키를 유효하지 않은 목록에 추가
                    if "API_KEY_INVALID" in retry_error_message or "API key not valid" in retry_error_message:
                        INVALID_API_KEYS.add(api_key)
                        print(f"유효하지 않은 API 키: {api_key[:4]}... - 다른 키로 재시도합니다.")
                        
                        # 다른 API 키로 재시도
                        if len(GOOGLE_API_KEYS) > 1 and len(INVALID_API_KEYS) < len(GOOGLE_API_KEYS):
                            return generate_ai_response(prompt, model_name)
                    
                    return f"Error generating AI response after retry: {retry_error_message}"
        
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

def generate_major_summary(chapters, model_name="gemini-2.5-pro-preview-03-25"):
    # 각 회차의 제목과 내용을 결합
    combined_text = ""
    for idx, chapter in enumerate(chapters, 1):
        combined_text += f"## 회차 {idx}: {chapter.title}\n\n"
        combined_text += f"{chapter.content}\n\n"
    
    prompt = f"""다음은 소설의 여러 회차입니다. 이 회차들의 내용을 종합하여 전체 흐름이 잘 드러나도록 1000자 내외로 요약해주세요.
    주요 사건, 인물의 발전, 플롯의 전개를 중심으로 요약하되, 개인적인 감상이나 평가는 포함하지 마세요.
    각 회차의 중요한 내용이 모두 포함되도록 하되, 전체적인 스토리 흐름을 파악할 수 있게 요약해주세요.
    
    {combined_text}"""
    
    return generate_ai_response(prompt, model_name)

# Routes
@app.route('/')
def index():
    novels = Novel.query.all()
    return render_template('index.html', novels=novels)

@app.route('/novel/new', methods=['GET', 'POST'])
def new_novel():
    if request.method == 'POST':
        title = request.form.get('title')
        novel = Novel(title=title)
        db.session.add(novel)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel.id))
    return render_template('new_novel.html')

@app.route('/novel/<int:novel_id>/edit')
def edit_novel(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.order).all()
    characters = Character.query.filter_by(novel_id=novel_id).order_by(Character.order).all()
    settings = Setting.query.filter_by(novel_id=novel_id).order_by(Setting.order).all()
    major_summaries = MajorSummary.query.filter_by(novel_id=novel_id).all()
    
    # 프롬프트 가져오기
    system_prompts = Prompt.query.filter_by(novel_id=novel_id, prompt_type='system').all()
    top_prompts = Prompt.query.filter_by(novel_id=novel_id, prompt_type='top').all()
    bottom_prompts = Prompt.query.filter_by(novel_id=novel_id, prompt_type='bottom').all()
    
    # 세션에서 선택된 프롬프트 가져오기
    selected_system_prompt = session.get(f'novel_{novel_id}_system_prompt', None)
    selected_top_prompt = session.get(f'novel_{novel_id}_top_prompt', None)
    selected_bottom_prompt = session.get(f'novel_{novel_id}_bottom_prompt', None)
    
    # 사용 가능한 모델 목록
    models = {
        'main': ['gemini-2.5-pro-preview-03-25', 'gemini-2.0-flash-thinking-exp-01-21'],
        'assistant': ['gemini-2.0-flash', 'gemini-2.0-flash-thinking-exp-01-21']
    }
    
    return render_template(
        'edit_novel.html', 
        novel=novel, 
        chapters=chapters, 
        characters=characters, 
        settings=settings,
        major_summaries=major_summaries,
        system_prompts=system_prompts,
        top_prompts=top_prompts,
        bottom_prompts=bottom_prompts,
        selected_system_prompt=selected_system_prompt,
        selected_top_prompt=selected_top_prompt,
        selected_bottom_prompt=selected_bottom_prompt,
        models=models
    )

@app.route('/novel/<int:novel_id>/chapter/new', methods=['POST'])
def new_chapter(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    title = request.form.get('title', 'Untitled Chapter')
    
    # Get the highest order value and add 1
    last_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.order.desc()).first()
    order = 1 if last_chapter is None else last_chapter.order + 1
    
    chapter = Chapter(title=title, content='', novel_id=novel_id, order=order)
    db.session.add(chapter)
    db.session.commit()
    
    return redirect(url_for('edit_chapter', novel_id=novel_id, chapter_id=chapter.id))

@app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>')
def edit_chapter(novel_id, chapter_id):
    novel = Novel.query.get_or_404(novel_id)
    chapter = Chapter.query.get_or_404(chapter_id)
    models = get_available_models()
    
    return render_template('edit_chapter.html', novel=novel, chapter=chapter, models=models)

@app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/save', methods=['POST'])
def save_chapter(novel_id, chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    chapter.title = request.form.get('title', chapter.title)
    chapter.content = request.form.get('content', chapter.content)
    
    # Generate summary if content changed
    if chapter.content and (not chapter.summary or 'regenerate_summary' in request.form):
        assistant_model = request.form.get('assistant_model', 'gemini-2.0-flash')
        chapter.summary = generate_summary(chapter.content, assistant_model)
    
    db.session.commit()
    return redirect(url_for('edit_chapter', novel_id=novel_id, chapter_id=chapter_id))

@app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/check_spelling', methods=['POST'])
def check_chapter_spelling(novel_id, chapter_id):
    content = request.form.get('content', '')
    assistant_model = request.form.get('assistant_model', 'gemini-2.0-flash')
    
    result = check_spelling(content, assistant_model)
    return jsonify({'result': result})

@app.route('/novel/<int:novel_id>/chapter/reorder', methods=['POST'])
def reorder_chapters(novel_id):
    order_data = request.json.get('order', [])
    
    for item in order_data:
        chapter_id = item.get('id')
        new_order = item.get('order')
        
        chapter = Chapter.query.get(chapter_id)
        if chapter and chapter.novel_id == novel_id:
            chapter.order = new_order
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/novel/<int:novel_id>/character/new', methods=['POST'])
def new_character(novel_id):
    name = request.form.get('name', 'New Character')
    description = request.form.get('description', '')
    
    character = Character(name=name, description=description, novel_id=novel_id)
    db.session.add(character)
    db.session.commit()
    
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/character/<int:character_id>/edit', methods=['POST'])
def edit_character(novel_id, character_id):
    character = Character.query.get_or_404(character_id)
    character.name = request.form.get('name', character.name)
    character.description = request.form.get('description', character.description)
    
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/character/reorder', methods=['POST'])
def reorder_characters(novel_id):
    order_data = request.json.get('order', [])
    
    for item in order_data:
        character_id = item.get('id')
        new_order = item.get('order')
        
        character = Character.query.get(character_id)
        if character and character.novel_id == novel_id:
            character.order = new_order
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/novel/<int:novel_id>/setting/new', methods=['POST'])
def new_setting(novel_id):
    title = request.form.get('title', 'New Setting')
    content = request.form.get('content', '')
    
    setting = Setting(title=title, content=content, novel_id=novel_id)
    db.session.add(setting)
    db.session.commit()
    
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/setting/<int:setting_id>/edit', methods=['POST'])
def edit_setting(novel_id, setting_id):
    setting = Setting.query.get_or_404(setting_id)
    setting.title = request.form.get('title', setting.title)
    setting.content = request.form.get('content', setting.content)
    
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/setting/reorder', methods=['POST'])
def reorder_settings(novel_id):
    order_data = request.json.get('order', [])
    
    for item in order_data:
        setting_id = item.get('id')
        new_order = item.get('order')
        
        setting = Setting.query.get(setting_id)
        if setting and setting.novel_id == novel_id:
            setting.order = new_order
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/novel/<int:novel_id>/prompt/new', methods=['POST'])
def new_prompt(novel_id):
    name = request.form.get('name', 'New Prompt')
    content = request.form.get('content', '')
    prompt_type = request.form.get('prompt_type', 'system')
    
    prompt = Prompt(name=name, content=content, prompt_type=prompt_type, novel_id=novel_id)
    db.session.add(prompt)
    db.session.commit()
    
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/prompt/<int:prompt_id>/edit', methods=['POST'])
def edit_prompt(novel_id, prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    prompt.name = request.form.get('name', prompt.name)
    prompt.content = request.form.get('content', prompt.content)
    prompt.prompt_type = request.form.get('prompt_type', prompt.prompt_type)
    
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/ai_assist', methods=['POST'])
def ai_assist(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    
    # Get selected chapters for summaries
    summary_chapter_ids = request.form.getlist('summary_chapters')
    summary_chapters = Chapter.query.filter(Chapter.id.in_(summary_chapter_ids)).order_by(Chapter.order).all()
    
    # Get selected chapters for content
    content_chapter_ids = request.form.getlist('content_chapters')
    content_chapters = Chapter.query.filter(Chapter.id.in_(content_chapter_ids)).order_by(Chapter.order).all()
    
    # Get selected major summaries
    major_summary_ids = request.form.getlist('major_summaries')
    major_summaries = MajorSummary.query.filter(MajorSummary.id.in_(major_summary_ids)).all()
    
    # Get characters and settings in order
    characters = Character.query.filter_by(novel_id=novel_id).order_by(Character.order).all()
    settings = Setting.query.filter_by(novel_id=novel_id).order_by(Setting.order).all()
    
    # Get prompts
    system_prompt_id = request.form.get('system_prompt')
    top_prompt_id = request.form.get('top_prompt')
    bottom_prompt_id = request.form.get('bottom_prompt')
    
    # 선택된 프롬프트 세션에 저장
    session[f'novel_{novel_id}_system_prompt'] = system_prompt_id
    session[f'novel_{novel_id}_top_prompt'] = top_prompt_id
    session[f'novel_{novel_id}_bottom_prompt'] = bottom_prompt_id
    
    system_prompt = Prompt.query.get(system_prompt_id) if system_prompt_id else None
    top_prompt = Prompt.query.get(top_prompt_id) if top_prompt_id else None
    bottom_prompt = Prompt.query.get(bottom_prompt_id) if bottom_prompt_id else None
    
    # User input
    user_input = request.form.get('user_input', '')
    
    # Selected model
    main_model = request.form.get('main_model', 'gemini-2.5-pro-preview-03-25')
    
    # Build the prompt
    full_prompt = ""
    
    # 1. System instruction
    if system_prompt:
        full_prompt += f"시스템 지시사항:\n{system_prompt.content}\n\n"
    
    # 2. Top prompt
    if top_prompt:
        full_prompt += f"{top_prompt.content}\n\n"
    
    # 3. Settings
    if settings:
        full_prompt += "설정집:\n"
        for setting in settings:
            full_prompt += f"[{setting.title}]\n{setting.content}\n\n"
    
    # 4. Characters
    if characters:
        full_prompt += "캐릭터:\n"
        for character in characters:
            full_prompt += f"[{character.name}]\n{character.description}\n\n"
    
    # 5. Major summaries (대요약본)
    if major_summaries:
        full_prompt += "대요약본 (여러 회차의 종합 요약):\n"
        for major_summary in major_summaries:
            full_prompt += f"[{major_summary.title}]\n{major_summary.content}\n\n"
    
    # 6. Chapter summaries
    if summary_chapters:
        full_prompt += "회차 요약:\n"
        for chapter in summary_chapters:
            if chapter.summary:
                full_prompt += f"[{chapter.title}] 요약: {chapter.summary}\n\n"
    
    # 7. Chapter contents
    if content_chapters:
        full_prompt += "회차 본문:\n"
        for chapter in content_chapters:
            full_prompt += f"[{chapter.title}]\n{chapter.content}\n\n"
    
    # 8. User input (main prompt)
    full_prompt += f"메인 프롬프트:\n{user_input}\n\n"
    
    # 9. Bottom prompt
    if bottom_prompt:
        full_prompt += f"{bottom_prompt.content}"
    
    # Generate AI response
    ai_response = generate_ai_response(full_prompt, main_model)
    
    return render_template(
        'ai_response.html', 
        novel=novel, 
        ai_response=ai_response, 
        user_input=user_input,
        markdown=markdown
    )

@app.route('/api/chat', methods=['POST'])
def chat_api():
    user_message = request.json.get('message', '')
    model_name = request.json.get('model', 'gemini-2.0-flash')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    prompt = f"User: {user_message}\n\nAssistant:"
    
    try:
        response = generate_ai_response(prompt, model_name)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/novel/<int:novel_id>/delete', methods=['POST'])
def delete_novel(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    db.session.delete(novel)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/delete', methods=['POST'])
def delete_chapter(novel_id, chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    db.session.delete(chapter)
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/character/<int:character_id>/delete', methods=['POST'])
def delete_character(novel_id, character_id):
    character = Character.query.get_or_404(character_id)
    db.session.delete(character)
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/setting/<int:setting_id>/delete', methods=['POST'])
def delete_setting(novel_id, setting_id):
    setting = Setting.query.get_or_404(setting_id)
    db.session.delete(setting)
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/prompt/<int:prompt_id>/delete', methods=['POST'])
def delete_prompt(novel_id, prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    db.session.delete(prompt)
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/major_summary/new', methods=['POST'])
def new_major_summary(novel_id):
    title = request.form.get('title', 'New Major Summary')
    content = request.form.get('content', '')
    chapter_range = request.form.get('chapter_range', '')
    
    major_summary = MajorSummary(title=title, content=content, novel_id=novel_id, chapter_range=chapter_range)
    db.session.add(major_summary)
    db.session.commit()
    
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/major_summary/<int:major_summary_id>/edit', methods=['POST'])
def edit_major_summary(novel_id, major_summary_id):
    major_summary = MajorSummary.query.get_or_404(major_summary_id)
    major_summary.title = request.form.get('title', major_summary.title)
    major_summary.content = request.form.get('content', major_summary.content)
    major_summary.chapter_range = request.form.get('chapter_range', major_summary.chapter_range)
    
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/major_summary/<int:major_summary_id>/delete', methods=['POST'])
def delete_major_summary(novel_id, major_summary_id):
    major_summary = MajorSummary.query.get_or_404(major_summary_id)
    db.session.delete(major_summary)
    db.session.commit()
    return redirect(url_for('edit_novel', novel_id=novel_id))

@app.route('/novel/<int:novel_id>/major_summary/generate', methods=['POST'])
def generate_major_summary_route(novel_id):
    # 선택된 회차 ID 목록 가져오기
    chapter_ids = request.form.getlist('chapter_ids')
    
    if not chapter_ids:
        flash('요약할 회차를 선택해주세요.')
        return redirect(url_for('edit_novel', novel_id=novel_id))
    
    # 선택된 회차들 가져오기
    chapters = []
    for chapter_id in chapter_ids:
        chapter = Chapter.query.get(chapter_id)
        if chapter and chapter.novel_id == novel_id:
            chapters.append(chapter)
    
    # 회차 순서대로 정렬
    chapters.sort(key=lambda x: x.order)
    
    # 회차가 없으면 리다이렉트
    if not chapters:
        flash('유효한 회차를 선택해주세요.')
        return redirect(url_for('edit_novel', novel_id=novel_id))
    
    # 회차 범위 제목 생성 (예: "1-3장" 또는 "1, 3, 5장")
    if len(chapters) > 2 and all(chapters[i].order == chapters[i-1].order + 1 for i in range(1, len(chapters))):
        # 연속된 회차인 경우
        range_title = f"{chapters[0].order+1}-{chapters[-1].order+1}장"
    else:
        # 연속되지 않은 회차인 경우
        range_title = ", ".join([str(ch.order+1) for ch in chapters]) + "장"
    
    # 기본 제목 생성
    title = f"대요약본: {range_title}"
    
    try:
        # AI를 사용하여 대요약본 생성
        summary_content = generate_major_summary(chapters)
        
        # 대요약본 저장
        chapter_range = ",".join([str(ch.id) for ch in chapters])
        major_summary = MajorSummary(
            title=title,
            content=summary_content,
            novel_id=novel_id,
            chapter_range=chapter_range
        )
        
        db.session.add(major_summary)
        db.session.commit()
        
        flash('대요약본이 성공적으로 생성되었습니다.')
    except Exception as e:
        flash(f'대요약본 생성 중 오류가 발생했습니다: {str(e)}')
    
    return redirect(url_for('edit_novel', novel_id=novel_id))

# API 키 테스트 라우트
@app.route('/test_api_key', methods=['POST'])
def test_api_key():
    try:
        # 요청에서 API 키 목록 가져오기
        data = request.json
        api_keys_input = data.get('api_keys', '')
        
        # API 키 목록 처리
        api_keys_list = []
        for key in api_keys_input.split(','):
            key = key.strip()
            if key:  # 빈 문자열이 아닌 경우에만 추가
                api_keys_list.append(key)
        
        if not api_keys_list:
            return jsonify({
                'success': False,
                'message': 'API 키가 입력되지 않았습니다.'
            })
        
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
                
            return jsonify({
                'success': True,
                'message': f'{len(valid_keys)}개의 API 키가 유효합니다. {len(invalid_keys)}개의 API 키가 유효하지 않습니다.',
                'valid_count': len(valid_keys),
                'invalid_count': len(invalid_keys)
            })
        else:
            return jsonify({
                'success': False,
                'message': f'모든 API 키({len(api_keys_list)}개)가 유효하지 않습니다. 첫 번째 오류: {invalid_keys[0]["error"] if invalid_keys else "알 수 없는 오류"}',
                'errors': [item['error'] for item in invalid_keys]
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'API 키 테스트 중 오류가 발생했습니다: {str(e)}'
        })

# 애플리케이션 시작 시 데이터베이스 초기화
with app.app_context():
    db.create_all()
    print("Database initialized successfully!")

# AI 설정 변경 라우트
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global AI_TIMEOUT, AI_SAFETY_SETTINGS, AI_TEMPERATURE, AI_TOP_P, GOOGLE_API_KEYS, CURRENT_API_KEY_INDEX, INVALID_API_KEYS
    
    if request.method == 'POST':
        # 폼에서 설정 값 가져오기
        new_api_keys = request.form.get('api_key', '')
        new_timeout = request.form.get('timeout', '300')
        new_safety = request.form.get('safety_settings', 'off')
        new_temperature = request.form.get('temperature', '0.7')
        new_top_p = request.form.get('top_p', '0.9')
        
        # API 키 처리 (쉼표로 구분된 여러 키 지원)
        if new_api_keys:
            # 쉼표로 구분된 API 키 목록을 배열로 변환 (공백 제거 및 빈 키 필터링)
            new_api_keys_list = []
            for key in new_api_keys.split(','):
                key = key.strip()
                if key:  # 빈 문자열이 아닌 경우에만 추가
                    new_api_keys_list.append(key)
            
            print(f"새로운 API 키 목록: {len(new_api_keys_list)}개")
            for i, key in enumerate(new_api_keys_list):
                print(f"  키 {i+1}: {key[:4]}...{key[-4:] if len(key) > 8 else ''} (길이: {len(key)})")
            
            # 기존 API 키 목록과 다른 경우에만 업데이트
            if new_api_keys_list != GOOGLE_API_KEYS:
                # 환경 변수 설정 (쉼표로 구분된 문자열로 저장)
                os.environ['GOOGLE_API_KEY'] = ','.join(new_api_keys_list)
                print(f"환경 변수에 저장된 API 키: {os.environ['GOOGLE_API_KEY']}")
                
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
                    flash(f'{len(GOOGLE_API_KEYS)}개의 Google API 키가 성공적으로 업데이트되었습니다.')
                else:
                    flash('API 키가 설정되지 않았습니다.')
        
        # 환경 변수 설정
        os.environ['AI_TIMEOUT'] = new_timeout
        os.environ['AI_SAFETY_SETTINGS'] = new_safety
        os.environ['AI_TEMPERATURE'] = new_temperature
        os.environ['AI_TOP_P'] = new_top_p
        
        # 전역 변수 업데이트
        AI_TIMEOUT = int(new_timeout)
        AI_SAFETY_SETTINGS = new_safety
        AI_TEMPERATURE = float(new_temperature)
        AI_TOP_P = float(new_top_p)
        
        return redirect(url_for('settings'))
    
    # API 키 목록을 쉼표로 구분된 문자열로 변환
    api_keys_str = ", ".join(GOOGLE_API_KEYS) if GOOGLE_API_KEYS else ""
    
    # API 키 마스킹 처리 (보안을 위해)
    masked_api_keys = ""
    if api_keys_str:
        # 각 API 키에 대해 마스킹 처리
        masked_keys = []
        for key in GOOGLE_API_KEYS:
            if len(key) > 8:
                masked_key = key[:4] + '*' * (len(key) - 8) + key[-4:]
            else:
                masked_key = key
            masked_keys.append(masked_key)
        
        masked_api_keys = ", ".join(masked_keys)
    
    return render_template('settings.html', 
                          api_key=masked_api_keys,
                          timeout=AI_TIMEOUT, 
                          safety_settings=AI_SAFETY_SETTINGS,
                          temperature=AI_TEMPERATURE,
                          top_p=AI_TOP_P)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
