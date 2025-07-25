from flask import Flask, render_template, request, abort, session, redirect
import os
import git
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
import re
import chardet

# Получаем абсолютный путь к директории проекта
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__,
            template_folder=os.path.join(basedir, 'templates'),
            static_folder=os.path.join(basedir, 'static'))

app.secret_key = 'your_secret_key_here_12345'
REPOS_DIR = os.path.join(basedir, 'repos')

os.makedirs(REPOS_DIR, exist_ok=True)


def detect_encoding(file_path):
    """Определяет кодировку файла"""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)  # Читаем первые 10KB для определения кодировки
            result = chardet.detect(raw_data)
            encoding = result['encoding']
            confidence = result['confidence']

            # Если уверенность высокая, используем определенную кодировку
            if confidence > 0.7 and encoding:
                return encoding
    except:
        pass

    # По умолчанию пробуем UTF-8, затем другие популярные кодировки
    return None


def read_text_file(file_path):
    """Читает текстовый файл с автоматическим определением кодировки"""
    encodings_to_try = ['utf-8', 'utf-8-sig', 'cp1251', 'cp1252', 'iso-8859-1', 'ascii']

    # Сначала пробуем определить кодировку
    detected_encoding = detect_encoding(file_path)
    if detected_encoding:
        encodings_to_try.insert(0, detected_encoding)

    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read(), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            continue

    # Если все кодировки не сработали, пробуем игнорировать ошибки
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(), 'utf-8 (с игнорированием ошибок)'
    except:
        pass

    raise Exception("Не удалось прочитать файл с поддерживаемыми кодировками")


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

    # Проверяем по расширению
    if '.' in file_path:
        ext = file_path.split('.')[-1].lower()
        if ext in text_extensions:
            return True

    # Проверяем специальные имена файлов
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

    # Проверяем, является ли файл текстовым
    if not is_text_file(file_path):
        # Для бинарных файлов показываем сообщение
        try:
            file_size = os.path.getsize(full_path)
            if file_size > 10 * 1024 * 1024:  # Больше 10MB
                return f"<pre>Файл слишком большой для просмотра ({file_size / (1024 * 1024):.1f} MB)</pre>"
        except:
            pass

    try:
        # Читаем файл с автоматическим определением кодировки
        content, encoding_used = read_text_file(full_path)

        # Определяем язык по расширению файла
        lexer = TextLexer()
        lang_map = {
            'py': 'python',
            'js': 'javascript',
            'jsx': 'jsx',
            'ts': 'typescript',
            'tsx': 'tsx',
            'html': 'html',
            'htm': 'html',
            'css': 'css',
            'scss': 'scss',
            'sass': 'sass',
            'less': 'less',
            'json': 'json',
            'xml': 'xml',
            'sql': 'sql',
            'sh': 'bash',
            'bash': 'bash',
            'md': 'markdown',
            'markdown': 'markdown',
            'yaml': 'yaml',
            'yml': 'yaml',
            'java': 'java',
            'cpp': 'cpp',
            'c': 'c',
            'h': 'c',
            'cs': 'csharp',
            'php': 'php',
            'rb': 'ruby',
            'go': 'go',
            'rs': 'rust',
            'swift': 'swift',
            'kt': 'kotlin',
            'kts': 'kotlin',
            'r': 'r',
            'pl': 'perl',
            'pm': 'perl',
            'lua': 'lua',
            'scala': 'scala',
            'groovy': 'groovy',
            'dart': 'dart',
            'ini': 'ini',
            'toml': 'toml',
            'cfg': 'ini',
            'conf': 'ini',
            'properties': 'properties',
            'graphql': 'graphql',
            'proto': 'protobuf'
        }

        # Определяем язык
        language = 'text'
        if '.' in file_path:
            ext = file_path.split('.')[-1].lower()
            if ext in lang_map:
                language = lang_map[ext]
        else:
            # Проверяем специальные имена файлов
            filename = os.path.basename(file_path).lower()
            if 'requirements' in filename:
                language = 'text'  # Для requirements.txt
            elif 'dockerfile' in filename:
                language = 'docker'
            elif 'makefile' in filename:
                language = 'make'
            elif filename in ['license', 'changelog', 'readme']:
                language = 'markdown'

        # Получаем лексер
        try:
            lexer = get_lexer_by_name(language)
        except:
            lexer = TextLexer()

        # Выбираем стиль в зависимости от темы
        theme = session.get('theme', 'light')
        style = 'monokai' if theme == 'dark' else 'default'

        formatter = HtmlFormatter(style=style, cssclass="highlight")
        highlighted = highlight(content, lexer, formatter)

        # Добавляем информацию о кодировке и кнопку копирования
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
        # Бинарный файл
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
                # Читаем README с автоматическим определением кодировки
                content, _ = read_text_file(readme_path)

                # Определяем тему для подсветки
                theme = session.get('theme', 'light')

                # Обрабатываем блоки кода в README.md
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

                    # Экранируем код для data-атрибута
                    escaped_code = code.replace('\\', '\\\\').replace('"', '&quot;').replace('\n', '\\n').replace('\r',
                                                                                                                  '')

                    # Кнопка копирования только с иконкой для README.md
                    copy_button = f'''
                    <button class="readme-copy-btn" 
                            onclick="copyCode(this)" 
                            data-code="{escaped_code}">
                        <i class="fas fa-copy"></i>
                    </button>
                    '''

                    return f'<div class="readme-code-header">{copy_button}{highlighted}</div>'

                # Обрабатываем блоки кода ```language
                content = re.sub(r'```(\w+)?\n(.*?)\n```', code_block_replacer, content, flags=re.DOTALL)

                # Конвертируем остальной Markdown
                html_content = markdown.markdown(content, extensions=[
                    'tables',
                    'nl2br'
                ])

                return html_content

            except Exception as e:
                return f"<p>Ошибка при чтении README.md: {str(e)}</p>"

    return None


@app.route('/toggle-theme')
def toggle_theme():
    """Переключение темы"""
    current_theme = session.get('theme', 'light')
    session['theme'] = 'dark' if current_theme == 'light' else 'light'
    return_to = request.args.get('return_to', '/')
    return redirect(return_to)


@app.route('/')
def index():
    repos = []
    for name in os.listdir(REPOS_DIR):
        repo_path = os.path.join(REPOS_DIR, name)
        if os.path.isdir(repo_path):
            try:
                repo = git.Repo(repo_path)
                last_commit = next(repo.iter_commits(max_count=1))
                repos.append({
                    'name': name,
                    'last_commit': last_commit.summary,
                    'last_commit_date': last_commit.committed_datetime.strftime('%Y-%m-%d'),
                    'branch': repo.active_branch.name if not repo.head.is_detached else 'detached'
                })
            except Exception as e:
                repos.append({
                    'name': name,
                    'last_commit': 'Ошибка загрузки',
                    'last_commit_date': '',
                    'branch': 'unknown'
                })

    theme = session.get('theme', 'light')
    return render_template('index.html', repos=repos, theme=theme)


@app.route('/repo/<repo_name>')
@app.route('/repo/<repo_name>/<path:subpath>')
def view_repo(repo_name, subpath=''):
    repo_path = os.path.join(REPOS_DIR, repo_name)
    if not os.path.exists(repo_path):
        abort(404)

    try:
        repo = git.Repo(repo_path)

        # Если указан конкретный файл - показываем его содержимое
        full_subpath = os.path.join(repo_path, subpath) if subpath else repo_path

        if os.path.isfile(full_subpath):
            # Это файл - показываем его содержимое
            content = get_file_content(repo_path, subpath)
            if content is None:
                abort(404)
            theme = session.get('theme', 'light')
            return render_template('file_content.html',
                                   repo_name=repo_name,
                                   file_path=subpath,
                                   content=content,
                                   theme=theme)

        # Это папка - показываем содержимое
        tree_items = []
        commits = list(repo.iter_commits(max_count=10))

        # Получаем содержимое текущей директории
        if subpath:
            # Для поддиректорий нужно найти соответствующий tree
            try:
                tree = repo.tree()
                for part in subpath.split('/'):
                    tree = tree[part]
                if tree.type == 'tree':
                    items = tree
                else:
                    # Это файл
                    content = get_file_content(repo_path, subpath)
                    theme = session.get('theme', 'light')
                    return render_template('file_content.html',
                                           repo_name=repo_name,
                                           file_path=subpath,
                                           content=content,
                                           theme=theme)
            except:
                abort(404)
        else:
            # Корневая директория
            items = repo.tree()

        # Преобразуем элементы в список для отображения
        if hasattr(items, 'trees'):
            # Это корневой tree
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
            # Это поддиректория
            for item in items:
                tree_items.append({
                    'name': item.name,
                    'type': 'dir' if item.type == 'tree' else 'file',
                    'path': item.path
                })

        # Получаем README.md для корневой директории
        readme_content = None
        if not subpath:  # Только для корня репозитория
            readme_content = get_readme_content(repo_path)

        # Путь для хлебных крошек
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
                               repo_name=repo_name,
                               repo=repo,
                               tree_items=tree_items,
                               commits=commits,
                               current_path=subpath,
                               path_parts=path_parts,
                               readme_content=readme_content,
                               theme=theme)

    except Exception as e:
        return f"Ошибка при открытии репозитория: {e}", 500


if __name__ == '__main__':
    app.run(debug=True)