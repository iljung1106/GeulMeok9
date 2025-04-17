from flask import render_template, request, redirect, url_for, jsonify, session, flash
import os
import markdown
from models import db, Novel, Chapter, Character, Setting, Prompt, MajorSummary, User, UserSettings
from ai_service import (
    generate_ai_response, check_spelling, generate_summary, 
    generate_major_summary, get_available_models, test_api_keys,
    update_api_keys, AI_TIMEOUT, AI_SAFETY_SETTINGS, 
    AI_TEMPERATURE, AI_TOP_P, GOOGLE_API_KEYS, review_chapter,
    transform_text_style, modify_chapter_with_instructions
)
from flask_login import login_user, logout_user, login_required, current_user

def init_routes(app):
    # 인증 관련 라우트
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            remember = 'remember' in request.form
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.check_password(password):
                login_user(user, remember=remember)
                flash(f'{username}님, 환영합니다!')
                
                # 로그인 후 원래 가려던 페이지로 리디렉션
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('index'))
            else:
                flash('사용자명 또는 비밀번호가 올바르지 않습니다.')
                
        return render_template('login.html')
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('로그아웃되었습니다.')
        return redirect(url_for('login'))
    
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            password_confirm = request.form.get('password_confirm')
            
            # 사용자명 유효성 검사 (영어, 숫자, 정해진 특수문자만 허용)
            import re
            username_pattern = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
            if not username_pattern.match(username):
                flash('사용자명은 영어, 숫자, 특수문자(_-.)만 사용할 수 있습니다.')
                return render_template('register.html')
            
            # 이메일 필수 확인
            if not email:
                flash('이메일은 필수 입력 항목입니다.')
                return render_template('register.html')
            
            # 유효성 검사
            if password != password_confirm:
                flash('비밀번호가 일치하지 않습니다.')
                return render_template('register.html')
                
            # 사용자명 중복 확인
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash('이미 사용 중인 사용자명입니다.')
                return render_template('register.html')
                
            # 이메일 중복 확인
            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                flash('이미 사용 중인 이메일입니다.')
                return render_template('register.html')
            
            # 사용자 생성
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            
            # 사용자 설정 생성
            user_settings = UserSettings(user=user)
            db.session.add(user_settings)
            
            db.session.commit()
            
            flash('회원가입이 완료되었습니다. 로그인해주세요.')
            return redirect(url_for('login'))
            
        return render_template('register.html')
    
    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        if request.method == 'POST':
            # 프로필 정보 업데이트
            email = request.form.get('email')
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            password_confirm = request.form.get('password_confirm')
            
            # 이메일 변경
            if email != current_user.email:
                # 이메일 중복 확인
                existing_email = User.query.filter_by(email=email).first()
                if existing_email and existing_email.id != current_user.id:
                    flash('이미 사용 중인 이메일입니다.')
                else:
                    current_user.email = email
                    flash('이메일이 업데이트되었습니다.')
            
            # 비밀번호 변경
            if current_password and new_password:
                if not current_user.check_password(current_password):
                    flash('현재 비밀번호가 올바르지 않습니다.')
                elif new_password != password_confirm:
                    flash('새 비밀번호가 일치하지 않습니다.')
                else:
                    current_user.set_password(new_password)
                    flash('비밀번호가 변경되었습니다.')
            
            db.session.commit()
            return redirect(url_for('profile'))
            
        return render_template('profile.html', user=current_user)

    # Routes
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            novels = Novel.query.filter_by(user_id=current_user.id).all()
        else:
            novels = []
        return render_template('index.html', novels=novels)

    @app.route('/novel/new', methods=['GET', 'POST'])
    @login_required
    def new_novel():
        if request.method == 'POST':
            title = request.form.get('title')
            novel = Novel(title=title, user_id=current_user.id)
            db.session.add(novel)
            db.session.commit()
            
            # 기본 프롬프트 추가
            # 1. 시스템 프롬프트
            system_prompt = Prompt(
                name="기본 시스템 프롬프트",
                content="당신의 역할은 카카오페이지와 네이버 시리즈, 문피아, 노벨피아의 인기 웹소설 작가로서 독자들이 몰입감 있게 읽을 수 있는 현대적인 문체로 글을 쓰는 것입니다.",
                prompt_type="system",
                novel_id=novel.id
            )
            
            # 2. 상단 프롬프트
            top_prompt = Prompt(
                name="기본 상단 프롬프트",
                content="2000글자 이상으로 작성하세요. 자연스러운 한국 웹소설 문체로 작성하세요.",
                prompt_type="top",
                novel_id=novel.id
            )
            
            # 3. 하단 프롬프트
            bottom_prompt = Prompt(
                name="기본 하단 프롬프트",
                content="쉼표 ','와 말줄임표 '…'의 사용을 최소화하세요. 유저가 작성한 내용을 반복해서 작성하지 말고, 필요한 이후 텍스트만 작성하세요.",
                prompt_type="bottom",
                novel_id=novel.id
            )
            
            db.session.add_all([system_prompt, top_prompt, bottom_prompt])
            db.session.commit()
            
            return redirect(url_for('edit_novel', novel_id=novel.id))
        return render_template('new_novel.html')

    @app.route('/novel/<int:novel_id>/edit')
    @login_required
    def edit_novel(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
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
        models = get_available_models()
        
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
    @login_required
    def new_chapter(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        title = request.form.get('title', 'Untitled Chapter')
        
        # Get the highest order value and add 1
        last_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.order.desc()).first()
        order = 1 if last_chapter is None else last_chapter.order + 1
        
        chapter = Chapter(title=title, content='', novel_id=novel_id, order=order)
        db.session.add(chapter)
        db.session.commit()
        
        return redirect(url_for('edit_chapter', novel_id=novel_id, chapter_id=chapter.id))

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>')
    @login_required
    def edit_chapter(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        models = get_available_models()
        
        return render_template('edit_chapter.html', novel=novel, chapter=chapter, models=models)

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/save', methods=['POST'])
    @login_required
    def save_chapter(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        chapter.title = request.form.get('title', chapter.title)
        chapter.content = request.form.get('content', chapter.content)
        
        # Generate summary if content changed
        if chapter.content and (not chapter.summary or 'regenerate_summary' in request.form):
            assistant_model = request.form.get('assistant_model', 'gemini-2.0-flash')
            chapter.summary = generate_summary(chapter.content, assistant_model)
        
        db.session.commit()
        return redirect(url_for('edit_chapter', novel_id=novel_id, chapter_id=chapter_id))

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/check_spelling', methods=['POST'])
    @login_required
    def check_chapter_spelling(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        content = request.form.get('content', '')
        assistant_model = request.form.get('assistant_model', 'gemini-2.0-flash')
        
        result = check_spelling(content, assistant_model)
        return jsonify({'result': result})

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/review', methods=['POST'])
    @login_required
    def review_chapter_route(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        content = request.form.get('content', '')
        title = request.form.get('title', '')
        assistant_model = request.form.get('assistant_model', 'gemini-2.5-pro-exp-03-25')
        
        try:
            # AI 서비스를 사용하여 회차 감평
            result = review_chapter(content, title, assistant_model)
            return jsonify({'result': result})
        except Exception as e:
            app.logger.error(f"회차 감평 오류: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/novel/<int:novel_id>/chapter/reorder', methods=['POST'])
    @login_required
    def reorder_chapters(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
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
    @login_required
    def new_character(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        name = request.form.get('name', 'New Character')
        description = request.form.get('description', '')
        
        character = Character(name=name, description=description, novel_id=novel_id)
        db.session.add(character)
        db.session.commit()
        
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/character/<int:character_id>/edit', methods=['POST'])
    @login_required
    def edit_character(novel_id, character_id):
        novel = Novel.query.get_or_404(novel_id)
        character = Character.query.get_or_404(character_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        character.name = request.form.get('name', character.name)
        character.description = request.form.get('description', character.description)
        
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/character/reorder', methods=['POST'])
    @login_required
    def reorder_characters(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
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
    @login_required
    def new_setting(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        title = request.form.get('title', 'New Setting')
        content = request.form.get('content', '')
        
        setting = Setting(title=title, content=content, novel_id=novel_id)
        db.session.add(setting)
        db.session.commit()
        
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/setting/<int:setting_id>/edit', methods=['POST'])
    @login_required
    def edit_setting(novel_id, setting_id):
        novel = Novel.query.get_or_404(novel_id)
        setting = Setting.query.get_or_404(setting_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        setting.title = request.form.get('title', setting.title)
        setting.content = request.form.get('content', setting.content)
        
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/setting/reorder', methods=['POST'])
    @login_required
    def reorder_settings(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
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
    @login_required
    def new_prompt(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        name = request.form.get('name', 'New Prompt')
        content = request.form.get('content', '')
        prompt_type = request.form.get('prompt_type', 'system')
        
        prompt = Prompt(name=name, content=content, prompt_type=prompt_type, novel_id=novel_id)
        db.session.add(prompt)
        db.session.commit()
        
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/prompt/<int:prompt_id>/edit', methods=['POST'])
    @login_required
    def edit_prompt(novel_id, prompt_id):
        novel = Novel.query.get_or_404(novel_id)
        prompt = Prompt.query.get_or_404(prompt_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        prompt.name = request.form.get('name', prompt.name)
        prompt.content = request.form.get('content', prompt.content)
        prompt.prompt_type = request.form.get('prompt_type', prompt.prompt_type)
        
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/ai_assist', methods=['POST'])
    @login_required
    def ai_assist(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        # Get selected chapters for summaries
        summary_chapter_ids = request.form.getlist('summary_chapters')
        summary_chapters = Chapter.query.filter(Chapter.id.in_(summary_chapter_ids)).order_by(Chapter.order).all() if summary_chapter_ids else []
        
        # Get selected chapters for content
        content_chapter_ids = request.form.getlist('content_chapters')
        content_chapters = Chapter.query.filter(Chapter.id.in_(content_chapter_ids)).order_by(Chapter.order).all() if content_chapter_ids else []
        
        # Get selected major summaries
        major_summary_ids = request.form.getlist('major_summaries')
        major_summaries = MajorSummary.query.filter(MajorSummary.id.in_(major_summary_ids)).all() if major_summary_ids else []
        
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
        
        # 프롬프트 유형 및 사용자 입력
        prompt_type = request.form.get('prompt_type', 'with_content')
        user_input = request.form.get('user_input', '')
        
        # 프롬프트 유형에 따른 기본 프롬프트 설정
        if prompt_type == 'no_content':
            # 콘티 없이 회차 작성
            # 이전 회차의 내용을 기반으로 다음 회차를 자동으로 생성하는 프롬프트
            user_input = "이전 회차의 내용을 기반으로 다음 회차를 자연스럽게 이어서 작성해주세요. 2000글자 이상의 분량으로, 흥미로운 전개와 캐릭터 상호작용을 포함해주세요."
        elif prompt_type == 'with_content':
            # 콘티에 따라 회차 작성 (기본값)
            if not user_input:
                user_input = "위 콘티를 바탕으로 회차를 작성해주세요."
        # 질문 및 기타 프롬프트는 사용자 입력 그대로 사용
        
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
    @login_required
    def chat_api():
        user_message = request.json.get('message', '')
        model_name = request.json.get('model', 'gemini-2.0-flash')
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        # 세션에서 대화 기록 가져오기 (없으면 빈 리스트로 초기화)
        chat_history = session.get('chat_history', [])
        
        # 새 사용자 메시지 추가
        chat_history.append({"role": "user", "content": user_message})
        
        # 대화 기록을 기반으로 프롬프트 구성
        prompt = "다음은 사용자와 AI 도우미 간의 대화입니다. 이전 대화 내용을 고려하여 응답해주세요.\n\n"
        
        for message in chat_history:
            if message["role"] == "user":
                prompt += f"User: {message['content']}\n\n"
            else:
                prompt += f"Assistant: {message['content']}\n\n"
        
        prompt += "Assistant:"
        
        try:
            response = generate_ai_response(prompt, model_name)
            
            # AI 응답을 대화 기록에 추가
            chat_history.append({"role": "assistant", "content": response})
            
            # 대화 기록이 너무 길어지면 오래된 메시지 제거 (최대 10개 메시지 쌍 유지)
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]
            
            # 세션에 업데이트된 대화 기록 저장
            session['chat_history'] = chat_history
            
            return jsonify({'response': response})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/chat/reset', methods=['POST'])
    @login_required
    def reset_chat():
        # 세션에서 대화 기록 삭제
        if 'chat_history' in session:
            session.pop('chat_history')
        
        return jsonify({'success': True, 'message': '대화 기록이 초기화되었습니다.'})

    @app.route('/api/transform-style', methods=['POST'])
    @login_required
    def transform_style():
        text = request.json.get('text', '')
        style_type = request.json.get('style_type', '')
        model_name = request.json.get('model', 'gemini-2.5-pro-exp-03-25')
        
        if not text:
            return jsonify({'error': '변환할 텍스트가 제공되지 않았습니다.'}), 400
        
        if style_type not in ['elaborate', 'concise']:
            return jsonify({'error': '지원되지 않는 문체 변환 유형입니다.'}), 400
        
        try:
            result = transform_text_style(text, style_type, model_name)
            return jsonify({'result': result})
        except Exception as e:
            app.logger.error(f"문체 변환 오류: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/transform-style', methods=['POST'])
    @login_required
    def transform_style_route(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        content = request.form.get('content', '')
        style = request.form.get('style', '')
        assistant_model = request.form.get('assistant_model', 'gemini-2.5-pro-exp-03-25')
        
        if not content:
            return jsonify({'error': '변환할 텍스트가 제공되지 않았습니다.'}), 400
        
        if style not in ['elaborate', 'concise']:
            return jsonify({'error': '지원되지 않는 문체 변환 유형입니다.'}), 400
        
        try:
            # HTML 태그 제거
            import re
            clean_content = re.sub(r'<[^>]*>', '', content)
            
            # AI 서비스를 사용하여 문체 변환
            result = transform_text_style(clean_content, style, assistant_model)
            return jsonify({'result': result})
        except Exception as e:
            app.logger.error(f"문체 변환 오류: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/modify-with-instructions', methods=['POST'])
    @login_required
    def modify_chapter_with_instructions_route(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        content = request.form.get('content', '')
        instructions = request.form.get('instructions', '')
        assistant_model = request.form.get('assistant_model', 'gemini-2.5-pro-exp-03-25')
        
        if not content:
            return jsonify({'error': '수정할 텍스트가 제공되지 않았습니다.'}), 400
        
        if not instructions:
            return jsonify({'error': '지시 사항이 제공되지 않았습니다.'}), 400
        
        try:
            # HTML 태그 제거
            import re
            clean_content = re.sub(r'<[^>]*>', '', content)
            
            # AI 서비스를 사용하여 지시 사항에 따라 회차 수정
            result = modify_chapter_with_instructions(clean_content, instructions, assistant_model)
            return jsonify({'result': result})
        except Exception as e:
            app.logger.error(f"회차 수정 오류: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/novel/<int:novel_id>/delete', methods=['POST'])
    @login_required
    def delete_novel(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(novel)
        db.session.commit()
        return redirect(url_for('index'))

    @app.route('/novel/<int:novel_id>/chapter/<int:chapter_id>/delete', methods=['POST'])
    @login_required
    def delete_chapter(novel_id, chapter_id):
        novel = Novel.query.get_or_404(novel_id)
        chapter = Chapter.query.get_or_404(chapter_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(chapter)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/character/<int:character_id>/delete', methods=['POST'])
    @login_required
    def delete_character(novel_id, character_id):
        novel = Novel.query.get_or_404(novel_id)
        character = Character.query.get_or_404(character_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(character)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/setting/<int:setting_id>/delete', methods=['POST'])
    @login_required
    def delete_setting(novel_id, setting_id):
        novel = Novel.query.get_or_404(novel_id)
        setting = Setting.query.get_or_404(setting_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(setting)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/prompt/<int:prompt_id>/delete', methods=['POST'])
    @login_required
    def delete_prompt(novel_id, prompt_id):
        novel = Novel.query.get_or_404(novel_id)
        prompt = Prompt.query.get_or_404(prompt_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(prompt)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/major_summary/new', methods=['POST'])
    @login_required
    def new_major_summary(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        title = request.form.get('title', 'New Major Summary')
        content = request.form.get('content', '')
        chapter_range = request.form.get('chapter_range', '')
        
        major_summary = MajorSummary(title=title, content=content, novel_id=novel_id, chapter_range=chapter_range)
        db.session.add(major_summary)
        db.session.commit()
        
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/major_summary/<int:major_summary_id>/edit', methods=['POST'])
    @login_required
    def edit_major_summary(novel_id, major_summary_id):
        novel = Novel.query.get_or_404(novel_id)
        major_summary = MajorSummary.query.get_or_404(major_summary_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        major_summary.title = request.form.get('title', major_summary.title)
        major_summary.content = request.form.get('content', major_summary.content)
        major_summary.chapter_range = request.form.get('chapter_range', major_summary.chapter_range)
        
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/major_summary/<int:major_summary_id>/delete', methods=['POST'])
    @login_required
    def delete_major_summary(novel_id, major_summary_id):
        novel = Novel.query.get_or_404(novel_id)
        major_summary = MajorSummary.query.get_or_404(major_summary_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
        db.session.delete(major_summary)
        db.session.commit()
        return redirect(url_for('edit_novel', novel_id=novel_id))

    @app.route('/novel/<int:novel_id>/major_summary/generate', methods=['POST'])
    @login_required
    def generate_major_summary_route(novel_id):
        novel = Novel.query.get_or_404(novel_id)
        
        # 소설 소유권 확인
        if novel.user_id != current_user.id and not current_user.is_admin:
            flash('이 소설에 접근할 권한이 없습니다.')
            return redirect(url_for('index'))
            
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
            # 각 회차의 제목과 내용 수집
            chapters_content = []
            for chapter in chapters:
                chapters_content.append({
                    'title': chapter.title,
                    'content': chapter.content
                })
            
            # 메인 모델 가져오기
            main_model = request.form.get('main_model', 'gemini-2.5-pro-exp-03-25')
            
            # 대요약본 생성
            summary_content = generate_major_summary(chapters_content, main_model)
            
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
    @login_required
    def test_api_key_route():
        try:
            # 요청에서 API 키 목록 가져오기
            data = request.json
            api_keys_input = data.get('api_keys', '')
            
            # API 키 테스트 실행
            result = test_api_keys(api_keys_input)
            return jsonify(result)
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'API 키 테스트 중 오류가 발생했습니다: {str(e)}'
            })

    # AI 설정 변경 라우트
    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        # 사용자 설정 가져오기
        user_settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        
        # 설정이 없으면 생성
        if not user_settings:
            user_settings = UserSettings(user_id=current_user.id)
            db.session.add(user_settings)
            db.session.commit()
        
        if request.method == 'POST':
            # 폼에서 설정 값 가져오기
            new_api_keys = request.form.get('api_key', '')
            new_timeout = request.form.get('timeout', '300')
            new_safety = request.form.get('safety_settings', 'off')
            new_temperature = request.form.get('temperature', '0.7')
            new_top_p = request.form.get('top_p', '0.9')
            
            # API 키 처리 (관리자만 가능)
            if current_user.is_admin and new_api_keys:
                success, message = update_api_keys(new_api_keys)
                if success:
                    # API 키를 사용자 설정에도 저장
                    user_settings.api_key = new_api_keys
                    db.session.commit()  # 변경사항 즉시 커밋
                    flash(message)
                else:
                    flash(message)
            elif not current_user.is_admin and new_api_keys:
                flash('API 키는 관리자만 변경할 수 있습니다.')
            
            # 사용자 설정 업데이트
            user_settings.ai_timeout = int(new_timeout)
            user_settings.ai_safety_settings = new_safety
            user_settings.ai_temperature = float(new_temperature)
            user_settings.ai_top_p = float(new_top_p)
            db.session.commit()
            
            flash('설정이 저장되었습니다.')
            return redirect(url_for('settings'))
        
        # API 키 마스킹 처리 (관리자만 볼 수 있음)
        masked_api_keys = ""
        if current_user.is_admin and GOOGLE_API_KEYS:
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
                            api_key=masked_api_keys if current_user.is_admin else "",
                            timeout=user_settings.ai_timeout, 
                            safety_settings=user_settings.ai_safety_settings,
                            temperature=user_settings.ai_temperature,
                            top_p=user_settings.ai_top_p,
                            is_admin=current_user.is_admin)
