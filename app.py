import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
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

# Configure Google AI API
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
else:
    print("Warning: GOOGLE_API_KEY not found in .env file")

# AI 설정 값
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "300"))  # 기본 타임아웃 300초로 증가
AI_SAFETY_SETTINGS = os.getenv("AI_SAFETY_SETTINGS", "off")  # 기본 검열 수준을 off로 설정

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

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)

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
        "main": ["gemini-2.5-pro-exp-03-25", "gemini-2.0-flash-thinking-exp-01-21", "gemini-2.0-flash"],
        "assistant": ["gemini-2.0-flash"]
    }

def generate_ai_response(prompt, model_name="gemini-2.5-pro-exp-03-25"):
    try:
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
        
        # 모델 생성 시 안전 설정 적용
        model = genai.GenerativeModel(model_name, safety_settings=safety_settings)
        
        # 응답 생성 (타임아웃 없이)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error generating AI response: {str(e)}"

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
        'main': ['gemini-2.5-pro-exp-03-25', 'gemini-2.0-flash-thinking-exp-01-21'],
        'assistant': ['gemini-2.0-flash', 'gemini-2.0-flash-thinking-exp-01-21']
    }
    
    return render_template(
        'edit_novel.html', 
        novel=novel, 
        chapters=chapters, 
        characters=characters, 
        settings=settings,
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
    main_model = request.form.get('main_model', 'gemini-2.5-pro-exp-03-25')
    
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
    
    # 5. Chapter summaries
    if summary_chapters:
        full_prompt += "회차 요약:\n"
        for chapter in summary_chapters:
            if chapter.summary:
                full_prompt += f"[{chapter.title}] 요약: {chapter.summary}\n\n"
    
    # 6. Chapter contents
    if content_chapters:
        full_prompt += "회차 본문:\n"
        for chapter in content_chapters:
            full_prompt += f"[{chapter.title}]\n{chapter.content}\n\n"
    
    # 7. User input (main prompt)
    full_prompt += f"메인 프롬프트:\n{user_input}\n\n"
    
    # 8. Bottom prompt
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

# 애플리케이션 시작 시 데이터베이스 초기화
with app.app_context():
    db.create_all()
    print("Database initialized successfully!")

# AI 설정 변경 라우트
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global AI_TIMEOUT, AI_SAFETY_SETTINGS
    
    if request.method == 'POST':
        # 폼에서 설정 값 가져오기
        new_timeout = request.form.get('timeout', '120')
        new_safety = request.form.get('safety_settings', 'moderate')
        
        # 환경 변수 설정
        os.environ['AI_TIMEOUT'] = new_timeout
        os.environ['AI_SAFETY_SETTINGS'] = new_safety
        
        # 전역 변수 업데이트
        AI_TIMEOUT = int(new_timeout)
        AI_SAFETY_SETTINGS = new_safety
        
        return redirect(url_for('settings'))
    
    return render_template('settings.html', 
                          timeout=AI_TIMEOUT, 
                          safety_settings=AI_SAFETY_SETTINGS)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
