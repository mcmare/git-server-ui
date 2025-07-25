from flask import Flask, render_template, request, abort, session, redirect, jsonify, flash, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import git
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
import re
import chardet
import subprocess
import shutil
from datetime import datetime
from urllib.parse import quote

# Получаем абсолютный путь к директории проекта
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__,
            template_folder=os.path.join(basedir, 'templates'),
            static_folder=os.path.join(basedir, 'static'))

# Конфигурация
app.config['SECRET_KEY'] = 'your_secret_key_here_12345'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "git_server.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация расширений
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'

REPOS_DIR = os.path.join(basedir, 'repos')
os.makedirs(REPOS_DIR, exist_ok=True)


# Модели базы данных
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)  # Для подтверждения администратором
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Repository(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', backref=db.backref('repositories', lazy=True))

    def __repr__(self):
        return f'<Repository {self.name}>'


# Callback для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Создание таблиц базы данных
with app.app_context():
    db.create_all()

    # Создаем администратора, если его нет
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@mcmare.ru', is_admin=True, is_active=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


# Функции для работы с файлами (остаются без изменений)
def detect_encoding(file_path):
    """Определяет кодировку файла"""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            result = chardet.detect(raw_data)
            encoding = result['encoding']
            confidence = result['confidence']
            if confidence > 0.7 and encoding:
                return encoding
    except:
        pass
    return None


def read_text_file(file_path):
    """Читает текстовый файл с автоматическим определением кодировки"""
    encodings_to_try = ['utf-8', 'utf-8-sig', 'cp1251', 'cp1252', 'iso-8859-1', 'ascii']
    detected_encoding = detect_encoding(file_path)
    if detected_encoding:
        encodings_to_try.insert(0, detected_encoding)

    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read(), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(), 'utf-8 (с игнорированием ошибок)'
    except:
        pass

    raise Exception("Не удалось прочитать файл")


def is_text_file(file_path):
    """Проверяет, является ли файл текстовым"""
    text_extensions = {
        'txt', 'md', 'markdown', 'rst', 'log', 'csv', 'json', 'xml', 'yml', 'yaml',
        'py', 'js', 'jsx', 'ts', 'tsx', 'html', 'htm', 'css', 'scss', 'sass', 'less',
        'php', 'rb', 'java', 'cpp', 'c', 'h', 'cs', 'go', 'rs', 'swift', 'kt', 'kts',
        'sh', 'bash', 'sql', 'r', 'pl', 'pm', 'lua', 'scala', 'groovy', 'dart',
        'ini', 'cfg', 'conf', 'config', 'env', 'toml', 'properties', 'gradle',
        'bat', 'cmd', 'ps1', 'vbs', 'sql', 'graphql', 'proto'
    }

    if '.' in file_path:
        ext = file_path.split('.')[-1].lower()
        if ext in text_extensions:
            return True

    filename = os.path.basename(file_path).lower()
    special_names = {
        'requirements', 'readme', 'license', 'changelog', 'contributing', 'authors',
        'dockerfile', 'makefile', 'rakefile', 'gemfile', 'composer', 'package',
        'webpack.config', 'vite.config', 'rollup.config', 'gulpfile', 'gruntfile',
        'procfile', 'manifest', 'cargo.toml', 'pom.xml', 'build.gradle'
    }

    for name in special_names:
        if name in filename:
            return True

    return False


def get_file_content(repo_path, file_path):
    """Получить содержимое файла с подсветкой синтаксиса"""
    full_path = os.path.join(repo_path, file_path)
    if not os.path.exists(full_path):
        return None

    if not is_text_file(file_path):
        try:
            file_size = os.path.getsize(full_path)
            if file_size > 10 * 1024 * 1024:
                return f"<pre>Файл слишком большой для просмотра ({file_size / (1024 * 1024):.1f} MB)</pre>"
        except:
            pass

    try:
        content, encoding_used = read_text_file(full_path)

        lexer = TextLexer()
        lang_map = {
            'py': 'python', 'js': 'javascript', 'jsx': 'jsx', 'ts': 'typescript', 'tsx': 'tsx',
            'html': 'html', 'htm': 'html', 'css': 'css', 'scss': 'scss', 'sass': 'sass', 'less': 'less',
            'json': 'json', 'xml': 'xml', 'sql': 'sql', 'sh': 'bash', 'bash': 'bash',
            'md': 'markdown', 'markdown': 'markdown', 'yaml': 'yaml', 'yml': 'yaml',
            'java': 'java', 'cpp': 'cpp', 'c': 'c', 'h': 'c', 'cs': 'csharp', 'php': 'php',
            'rb': 'ruby', 'go': 'go', 'rs': 'rust', 'swift': 'swift', 'kt': 'kotlin', 'kts': 'kotlin',
            'r': 'r', 'pl': 'perl', 'pm': 'perl', 'lua': 'lua', 'scala': 'scala', 'groovy': 'groovy',
            'dart': 'dart', 'ini': 'ini', 'toml': 'toml', 'cfg': 'ini', 'conf': 'ini',
            'properties': 'properties', 'graphql': 'graphql', 'proto': 'protobuf'
        }

        language = 'text'
        if '.' in file_path:
            ext = file_path.split('.')[-1].lower()
            if ext in lang_map:
                language = lang_map[ext]
        else:
            filename = os.path.basename(file_path).lower()
            if 'requirements' in filename:
                language = 'text'
            elif 'dockerfile' in filename:
                language = 'docker'
            elif 'makefile' in filename:
                language = 'make'
            elif filename in ['license', 'changelog', 'readme']:
                language = 'markdown'

        try:
            lexer = get_lexer_by_name(language)
        except:
            lexer = TextLexer()

        theme = session.get('theme', 'light')
        style = 'monokai' if theme == 'dark' else 'default'

        formatter = HtmlFormatter(style=style, cssclass="highlight")
        highlighted = highlight(content, lexer, formatter)

        escaped_content = content.replace('\\', '\\\\').replace('"', '&quot;').replace('\n', '\\n').replace('\r', '')
        copy_button = f'''
        <div class="code-header">
            <span class="language-badge badge bg-secondary">{language} ({encoding_used})</span>
            <button class="btn btn-sm btn-outline-secondary copy-btn" 
                    onclick="copyCode(this)" 
                    data-code="{escaped_content}">
                <i class="fas fa-copy"></i> Копировать
            </button>
        </div>
        '''
        return f'<div class="code-block-wrapper">{copy_button}<div class="file-content">{highlighted}</div></div>'

    except UnicodeDecodeError:
        try:
            file_size = os.path.getsize(full_path)
            return f"<pre>Бинарный файл - просмотр недоступен ({file_size / 1024:.1f} KB)</pre>"
        except:
            return "<pre>Бинарный файл - просмотр недоступен</pre>"
    except Exception as e:
        return f"<pre>Ошибка: {str(e)}</pre>"


def get_readme_content(repo_path):
    """Получить содержимое README.md с форматированием и подсветкой кода"""
    readme_files = ['README.md', 'readme.md', 'Readme.md']

    for readme_file in readme_files:
        readme_path = os.path.join(repo_path, readme_file)
        if os.path.exists(readme_path):
            try:
                content, _ = read_text_file(readme_path)
                theme = session.get('theme', 'light')

                def code_block_replacer(match):
                    language = match.group(1) if match.group(1) else 'text'
                    code = match.group(2)

                    try:
                        lexer = get_lexer_by_name(language)
                    except:
                        lexer = TextLexer()

                    style = 'monokai' if theme == 'dark' else 'default'
                    formatter = HtmlFormatter(style=style, cssclass="highlight")
                    highlighted = highlight(code, lexer, formatter)

                    escaped_code = code.replace('\\', '\\\\').replace('"', '&quot;').replace('\n', '\\n').replace('\r',
                                                                                                                  '')
                    copy_button = f'''
                    <button class="readme-copy-btn" 
                            onclick="copyCode(this)" 
                            data-code="{escaped_code}">
                        <i class="fas fa-copy"></i>
                    </button>
                    '''
                    return f'<div class="readme-code-header">{copy_button}{highlighted}</div>'

                content = re.sub(r'```(\w+)?\n(.*?)\n```', code_block_replacer, content, flags=re.DOTALL)
                html_content = markdown.markdown(content, extensions=['tables', 'nl2br'])
                return html_content

            except Exception as e:
                return f"<p>Ошибка при чтении README.md: {str(e)}</p>"

    return None


# 🛡️ Маршруты аутентификации

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Проверки
        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'error')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует', 'error')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'error')
            return render_template('register.html')

        # Создаем пользователя (неактивного)
        user = User(username=username, email=email, is_active=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Регистрация прошла успешно! Администратор должен подтвердить ваш аккаунт.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = bool(request.form.get('remember'))

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Ваш аккаунт ожидает подтверждения администратора', 'warning')
                return render_template('login.html')

            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# 👑 Админ-панель

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Доступ запрещен', 'error')
        return redirect(url_for('index'))

    users = User.query.all()
    repositories = Repository.query.all()

    return render_template('admin.html', users=users, repositories=repositories)


@app.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@login_required
def activate_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Доступ запрещен'}), 403

    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()

    return jsonify({'message': f'Пользователь {user.username} активирован'})


@app.route('/admin/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
def deactivate_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Доступ запрещен'}), 403

    user = User.query.get_or_404(user_id)
    if user.username == 'admin':
        return jsonify({'error': 'Нельзя деактивировать администратора'}), 400

    user.is_active = False
    db.session.commit()

    return jsonify({'message': f'Пользователь {user.username} деактивирован'})


@app.route('/admin/users/<int:user_id>/make_admin', methods=['POST'])
@login_required
def make_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Доступ запрещен'}), 403

    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()

    return jsonify({'message': f'Пользователь {user.username} теперь администратор'})


@app.route('/admin/users/<int:user_id>/remove_admin', methods=['POST'])
@login_required
def remove_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Доступ запрещен'}), 403

    user = User.query.get_or_404(user_id)
    if user.username == 'admin':
        return jsonify({'error': 'Нельзя снять права администратора у главного администратора'}), 400

    user.is_admin = False
    db.session.commit()

    return jsonify({'message': f'Пользователь {user.username} больше не администратор'})


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Доступ запрещен'}), 403

    user = User.query.get_or_404(user_id)
    if user.username == 'admin':
        return jsonify({'error': 'Нельзя удалить главного администратора'}), 400

    # Удаляем репозитории пользователя
    for repo in user.repositories:
        repo_path = os.path.join(REPOS_DIR, repo.name)
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
        db.session.delete(repo)

    db.session.delete(user)
    db.session.commit()

    return jsonify({'message': f'Пользователь {user.username} удален'})


# 🚀 API для управления репозиториями

@app.route('/api/repos', methods=['GET'])
@login_required
def api_list_repos():
    """API: Получить список репозиториев пользователя"""
    if current_user.is_admin:
        repos = Repository.query.all()
    else:
        repos = Repository.query.filter_by(owner_id=current_user.id).all()

    result = []
    for repo in repos:
        repo_path = os.path.join(REPOS_DIR, repo.name)
        if os.path.exists(repo_path):
            try:
                git_repo = git.Repo(repo_path)
                last_commit = next(git_repo.iter_commits(max_count=1))
                result.append({
                    'id': repo.id,
                    'name': repo.name,
                    'description': repo.description,
                    'is_public': repo.is_public,
                    'owner': repo.owner.username,
                    'last_commit': last_commit.summary,
                    'last_commit_date': last_commit.committed_datetime.isoformat(),
                    'branch': git_repo.active_branch.name if not git_repo.head.is_detached else 'detached'
                })
            except:
                result.append({
                    'id': repo.id,
                    'name': repo.name,
                    'description': repo.description,
                    'is_public': repo.is_public,
                    'owner': repo.owner.username,
                    'last_commit': 'Ошибка загрузки',
                    'last_commit_date': '',
                    'branch': 'unknown'
                })
        else:
            result.append({
                'id': repo.id,
                'name': repo.name,
                'description': repo.description,
                'is_public': repo.is_public,
                'owner': repo.owner.username,
                'last_commit': 'Репозиторий не найден',
                'last_commit_date': '',
                'branch': 'unknown'
            })

    return jsonify(result)


@app.route('/api/repos', methods=['POST'])
@login_required
def api_create_repo():
    """API: Создать новый репозиторий"""
    try:
        data = request.get_json()
        repo_name = data.get('name')
        description = data.get('description', '')
        is_public = data.get('is_public', False)

        if not repo_name:
            return jsonify({'error': 'Не указано имя репозитория'}), 400

        # Проверяем, что репозиторий с таким именем не существует
        if Repository.query.filter_by(name=repo_name).first():
            return jsonify({'error': 'Репозиторий с таким именем уже существует'}), 400

        # Создаем запись в базе данных
        repo = Repository(
            name=repo_name,
            description=description,
            is_public=is_public,
            owner_id=current_user.id
        )
        db.session.add(repo)
        db.session.commit()

        # Создаем bare репозиторий
        repo_path = os.path.join(REPOS_DIR, repo_name)
        git_repo = git.Repo.init(repo_path, bare=True)

        return jsonify({
            'message': f'Репозиторий {repo_name} создан успешно',
            'repo': {
                'id': repo.id,
                'name': repo.name,
                'description': repo.description,
                'is_public': repo.is_public,
                'owner': current_user.username
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/repos/<int:repo_id>/clone', methods=['POST'])
@login_required
def api_clone_repo(repo_id):
    """API: Клонировать внешний репозиторий"""
    try:
        repo = Repository.query.get_or_404(repo_id)

        # Проверяем права доступа
        if not current_user.is_admin and repo.owner_id != current_user.id:
            return jsonify({'error': 'Доступ запрещен'}), 403

        data = request.get_json()
        source_url = data.get('url')

        if not source_url:
            return jsonify({'error': 'Не указан URL источника'}), 400

        repo_path = os.path.join(REPOS_DIR, repo.name)

        if os.path.exists(repo_path):
            return jsonify({'error': 'Репозиторий уже существует'}), 400

        # Клонируем репозиторий
        git.Repo.clone_from(source_url, repo_path, bare=True)

        return jsonify({'message': f'Репозиторий клонирован успешно в {repo.name}'}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/repos/<int:repo_id>/delete', methods=['DELETE'])
@login_required
def api_delete_repo(repo_id):
    """API: Удалить репозиторий"""
    try:
        repo = Repository.query.get_or_404(repo_id)

        # Проверяем права доступа
        if not current_user.is_admin and repo.owner_id != current_user.id:
            return jsonify({'error': 'Доступ запрещен'}), 403

        # Удаляем папку с репозиторием
        repo_path = os.path.join(REPOS_DIR, repo.name)
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)

        # Удаляем запись из базы данных
        db.session.delete(repo)
        db.session.commit()

        return jsonify({'message': f'Репозиторий {repo.name} удален успешно'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# 🌐 Git HTTP протокол (остается без изменений)
@app.route('/git/<repo_name>/info/refs')
def git_info_refs(repo_name):
    repo_path = os.path.join(REPOS_DIR, repo_name)
    if not os.path.exists(repo_path):
        abort(404)

    service = request.args.get('service')
    if service:
        env = os.environ.copy()
        env['GIT_HTTP_EXPORT_ALL'] = '1'

        try:
            result = subprocess.run([
                'git', 'upload-pack', '--stateless-rpc', '--advertise-refs', repo_path
            ], capture_output=True, env=env)

            response = b'001e# service=git-upload-pack\n0000' + result.stdout
            return response, 200, {'Content-Type': 'application/x-git-upload-pack-advertisement'}
        except Exception as e:
            abort(500)

    abort(400)


@app.route('/git/<repo_name>/git-upload-pack', methods=['POST'])
def git_upload_pack(repo_name):
    repo_path = os.path.join(REPOS_DIR, repo_name)
    if not os.path.exists(repo_path):
        abort(404)

    try:
        env = os.environ.copy()
        process = subprocess.Popen([
            'git', 'upload-pack', '--stateless-rpc', repo_path
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

        stdout, stderr = process.communicate(request.data)

        if process.returncode != 0:
            abort(500)

        return stdout, 200, {'Content-Type': 'application/x-git-upload-pack-result'}
    except Exception as e:
        abort(500)


@app.route('/git/<repo_name>/git-receive-pack', methods=['POST'])
def git_receive_pack(repo_name):
    repo_path = os.path.join(REPOS_DIR, repo_name)
    if not os.path.exists(repo_path):
        abort(404)

    try:
        env = os.environ.copy()
        process = subprocess.Popen([
            'git', 'receive-pack', '--stateless-rpc', repo_path
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

        stdout, stderr = process.communicate(request.data)

        if process.returncode != 0:
            abort(500)

        return stdout, 200, {'Content-Type': 'application/x-git-receive-pack-result'}
    except Exception as e:
        abort(500)


# 🎨 Веб-интерфейс (с проверкой аутентификации)

@app.route('/')
@login_required
def index():
    if current_user.is_admin:
        repos = Repository.query.all()
    else:
        repos = Repository.query.filter_by(owner_id=current_user.id).all()

    repo_data = []
    for repo in repos:
        repo_path = os.path.join(REPOS_DIR, repo.name)
        if os.path.exists(repo_path):
            try:
                git_repo = git.Repo(repo_path)
                last_commit = next(git_repo.iter_commits(max_count=1))
                repo_data.append({
                    'id': repo.id,
                    'name': repo.name,
                    'description': repo.description,
                    'is_public': repo.is_public,
                    'owner': repo.owner.username,
                    'last_commit': last_commit.summary,
                    'last_commit_date': last_commit.committed_datetime.strftime('%Y-%m-%d'),
                    'branch': git_repo.active_branch.name if not git_repo.head.is_detached else 'detached'
                })
            except:
                repo_data.append({
                    'id': repo.id,
                    'name': repo.name,
                    'description': repo.description,
                    'is_public': repo.is_public,
                    'owner': repo.owner.username,
                    'last_commit': 'Ошибка загрузки',
                    'last_commit_date': '',
                    'branch': 'unknown'
                })
        else:
            repo_data.append({
                'id': repo.id,
                'name': repo.name,
                'description': repo.description,
                'is_public': repo.is_public,
                'owner': repo.owner.username,
                'last_commit': 'Репозиторий не найден',
                'last_commit_date': '',
                'branch': 'unknown'
            })

    theme = session.get('theme', 'light')
    return render_template('index.html', repos=repo_data, theme=theme)


# ... остальные маршруты веб-интерфейса (добавим проверку аутентификации) ...

@app.route('/repo/<int:repo_id>')
@app.route('/repo/<int:repo_id>/<path:subpath>')
@login_required
def view_repo(repo_id, subpath=''):
    repo = db.session.get(Repository, repo_id)
    if not repo:
        abort(404)

    # Проверяем права доступа
    if not repo.is_public and not current_user.is_admin and repo.owner_id != current_user.id:
        abort(403)

    repo_path = os.path.join(REPOS_DIR, repo.name)
    if not os.path.exists(repo_path):
        abort(404)

    try:
        git_repo = git.Repo(repo_path)

        full_subpath = os.path.join(repo_path, subpath) if subpath else repo_path

        if os.path.isfile(full_subpath):
            content = get_file_content(repo_path, subpath)
            if content is None:
                abort(404)
            theme = session.get('theme', 'light')
            return render_template('file_content.html',
                                   repo=repo,
                                   file_path=subpath,
                                   content=content,
                                   theme=theme)

        tree_items = []
        commits = list(git_repo.iter_commits(max_count=10))

        if subpath:
            try:
                tree = git_repo.tree()
                for part in subpath.split('/'):
                    tree = tree[part]
                if tree.type == 'tree':
                    items = tree
                else:
                    content = get_file_content(repo_path, subpath)
                    return render_template('file_content.html',
                                           repo=repo,
                                           file_path=subpath,
                                           content=content,
                                           theme=session.get('theme', 'light'))
            except:
                abort(404)
        else:
            items = git_repo.tree()

        if hasattr(items, 'trees'):
            for item in items.trees:
                tree_items.append({
                    'name': item.name,
                    'type': 'dir',
                    'path': item.path
                })
            for item in items.blobs:
                tree_items.append({
                    'name': item.name,
                    'type': 'file',
                    'path': item.path
                })
        else:
            for item in items:
                tree_items.append({
                    'name': item.name,
                    'type': 'dir' if item.type == 'tree' else 'file',
                    'path': item.path
                })

        readme_content = None
        if not subpath:
            readme_content = get_readme_content(repo_path)

        path_parts = []
        if subpath:
            parts = subpath.split('/')
            for i in range(len(parts)):
                path_parts.append({
                    'name': parts[i],
                    'path': '/'.join(parts[:i + 1])
                })

        theme = session.get('theme', 'light')
        return render_template('repo.html',
                               repo=repo,
                               git_repo=git_repo,
                               tree_items=tree_items,
                               commits=commits,
                               current_path=subpath,
                               path_parts=path_parts,
                               readme_content=readme_content,
                               theme=theme)

    except Exception as e:
        return f"Ошибка при открытии репозитория: {e}", 500


@app.route('/toggle-theme')
@login_required
def toggle_theme():
    current_theme = session.get('theme', 'light')
    session['theme'] = 'dark' if current_theme == 'light' else 'light'
    return_to = request.args.get('return_to', url_for('index'))
    return redirect(return_to)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)