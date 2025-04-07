from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()

# 사용자 모델
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    novels = db.relationship('Novel', backref='author', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    # 사용자 관계 추가
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

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

# 사용자별 설정 모델
class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    api_key = db.Column(db.Text, nullable=True)  # 개인 API 키 (쉼표로 구분된 여러 키)
    ai_timeout = db.Column(db.Integer, default=300)
    ai_safety_settings = db.Column(db.String(20), default='off')
    ai_temperature = db.Column(db.Float, default=0.7)
    ai_top_p = db.Column(db.Float, default=0.9)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='settings', lazy=True)
