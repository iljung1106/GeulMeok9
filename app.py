import os
from flask import Flask
import jinja2
import sys
from dotenv import load_dotenv
from flask_login import LoginManager

# UTF-8 인코딩 설정
if sys.platform.startswith('win'):
    import locale
    locale.setlocale(locale.LC_ALL, 'Korean_Korea.utf8')

# Load environment variables
load_dotenv()

# 애플리케이션 초기화
def create_app():
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
    
    # 데이터베이스 초기화
    from models import db, User, UserSettings
    db.init_app(app)
    
    # 로그인 매니저 초기화
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = '이 페이지에 접근하려면 로그인이 필요합니다.'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # 라우트 초기화
    from routes import init_routes
    init_routes(app)
    
    # 애플리케이션 시작 시 데이터베이스 초기화 및 관리자 계정 생성
    with app.app_context():
        db.create_all()
        print("Database initialized successfully!")
        
        # 관리자 계정 생성 (없는 경우)
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', is_admin=True)
            admin.set_password('password1234')  # 변경된 기본 비밀번호
            db.session.add(admin)
            
            # 관리자 설정 생성
            admin_settings = UserSettings(user=admin)
            db.session.add(admin_settings)
            
            db.session.commit()
            print("Admin account created successfully!")
        
        # 관리자 계정의 API 키를 환경 변수에 로드
        admin_settings = UserSettings.query.filter_by(user_id=admin.id).first()
        if admin_settings and admin_settings.api_key:
            os.environ['GOOGLE_API_KEY'] = admin_settings.api_key
            print(f"API 키가 관리자 설정에서 로드되었습니다: {len(admin_settings.api_key.split(','))}개의 키")
            # AI 서비스 모듈에 API 키 업데이트 알림
            from ai_service import update_api_keys
            update_api_keys(admin_settings.api_key)
    
    return app

# 애플리케이션 실행
if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)